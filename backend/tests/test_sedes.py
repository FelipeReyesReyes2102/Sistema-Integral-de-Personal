"""Sedes: aislamiento entre sedes, jefes de la misma sede, cumpleaños y festivos por sede, cambio de sede (solo
super administrador) y administradores con más de una sede."""
from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AdminSede, Festivo, Sede, Turno, Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.seed import main as seed

seed()
HOY = date.today()


def entrar(usuario, pwd, sede=None):
    c = TestClient(app)
    r = c.post("/api/auth/login-json", json={"usuario": usuario, "password": pwd})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    if sede:
        c.headers["X-Sede-Id"] = str(sede)
    return c


@pytest.fixture(scope="module")
def mundo():
    """Sede Medellín con su administrador, jefe, empleado (con cumpleaños), turno y festivo; y un super admin."""
    with SessionLocal() as db:
        mx = sede_principal(db)
        med = db.query(Sede).filter(Sede.nombre == "O-Tek Colombia - Medellín").first()
        if med is None:
            med = Sede(nombre="O-Tek Colombia - Medellín", ubicacion_microsoft="O-Tek Colombia - Medellín",
                       zona_horaria="America/Bogota")
            db.add(med)
            db.commit()
        pwd = hash_password("Clave12345")

        def usuario(nomina, nombre, email, rol="oficina", **kw):
            u = db.query(Usuario).filter(Usuario.numero_empleado == nomina).first()
            if u is None:
                u = Usuario(numero_empleado=nomina, nombre=nombre, email=email, rol=rol, password_hash=pwd,
                            fecha_ingreso=date(2021, 1, 4), **kw)
                db.add(u)
                db.commit()
            return u

        turno = db.query(Turno).filter(Turno.sede_id == med.id, Turno.nombre == "Oficina Medellín").first()
        if turno is None:
            turno = Turno(sede_id=med.id, nombre="Oficina Medellín", hora_entrada=time(7), hora_salida=time(16),
                          horas_jornada=8)
            db.add(turno)
            db.commit()
        admin_med = usuario("M-1", "Admin Medellín", "admin.med@o-tek.com", rol="admin", sede_id=med.id)
        jefe_med = usuario("M-2", "Jefe Medellín", "jefe.med@o-tek.com", es_jefe=True, sede_id=med.id)
        cumple = HOY + timedelta(days=10)
        emp_med = usuario("M-3", "Empleado Medellín", "emp.med@o-tek.com", sede_id=med.id, jefe_id=jefe_med.id,
                          turno_id=turno.id, fecha_nacimiento=date(1990, cumple.month, min(cumple.day, 28)))
        usuario("S-1", "Super Sedes", "super.sedes@o-tek.com", rol="superadmin", sede_id=mx.id)
        festivo = date(HOY.year, 7, 20)  # Independencia de Colombia
        if not db.query(Festivo).filter(Festivo.sede_id == med.id, Festivo.fecha == festivo).first():
            db.add(Festivo(sede_id=med.id, fecha=festivo, nombre="Independencia de Colombia"))
            db.commit()
        return {"mx": mx.id, "med": med.id, "admin_med": admin_med.id, "jefe_med": jefe_med.id, "emp_med": emp_med.id,
                "turno_med": turno.id, "festivo": festivo.isoformat(), "cumple_emp": emp_med.fecha_nacimiento}


def test_admin_solo_ve_su_sede(mundo):
    mx = entrar("admin@empresa.com", "Admin123")
    nombres = {u["nombre"] for u in mx.get("/api/usuarios").json()}
    assert "Ana López" in nombres and "Empleado Medellín" not in nombres
    assert mx.get(f"/api/usuarios/{mundo['emp_med']}").status_code == 403
    assert mx.post(f"/api/usuarios/{mundo['emp_med']}/password-temporal").status_code == 404
    assert mx.delete(f"/api/usuarios/{mundo['emp_med']}").status_code == 404
    assert mx.get(f"/api/periodos?usuario_id={mundo['emp_med']}").status_code == 403
    equipo = mx.get(f"/api/calendario/equipo?anio={HOY.year}&mes={HOY.month}").json()
    assert all(e["nombre"] != "Empleado Medellín" for e in equipo["empleados"])
    assert all(t["sede_id"] == mundo["mx"] for t in mx.get("/api/turnos").json())
    # El administrador de Medellín, igual: solo su sede
    med = entrar("admin.med@o-tek.com", "Clave12345")
    assert {u["nombre"] for u in med.get("/api/usuarios").json()} >= {"Empleado Medellín", "Jefe Medellín"}
    assert "Ana López" not in {u["nombre"] for u in med.get("/api/usuarios").json()}
    assert [s["nombre"] for s in med.get("/api/auth/me").json()["sedes"]] == ["O-Tek Colombia - Medellín"]


def test_cumpleanos_y_festivos_por_sede(mundo):
    emp = entrar("emp.med@o-tek.com", "Clave12345")
    cal = emp.get(f"/api/calendario?anio={HOY.year}").json()
    assert any(f["fecha"] == mundo["festivo"] for f in cal["festivos"])
    assert not any(f["nombre"] == "Navidad" for f in cal["festivos"])  # festivos de México no aplican
    ana = entrar("ana@empresa.com", "Cambiar123")
    cal_mx = ana.get(f"/api/calendario?anio={HOY.year}").json()
    assert not any(c["nombre"] == "Empleado Medellín" for c in cal_mx["cumpleanos"])
    assert not any(f["fecha"] == mundo["festivo"] for f in cal_mx["festivos"])
    cal_jefe = entrar("jefe.med@o-tek.com", "Clave12345").get(f"/api/calendario?anio={HOY.year}").json()
    assert any(c["nombre"] == "Empleado Medellín" for c in cal_jefe["cumpleanos"])


def test_jefes_solo_de_la_misma_sede(mundo):
    mx = entrar("admin@empresa.com", "Admin123")
    assert all(j["sede_id"] == mundo["mx"] for j in mx.get("/api/jefes").json())
    datos = {"numero_empleado": "MX-9", "nombre": "Nuevo MX", "email": "nuevo.mx@o-tek.com", "rol": "oficina",
             "fecha_ingreso": "2023-01-02", "jefe_id": mundo["jefe_med"]}
    r = mx.post("/api/usuarios", json=datos)
    assert r.status_code == 400 and "misma sede" in r.json()["detail"]
    # No puede registrar empleados en otra sede ni usar su turno
    r = mx.post("/api/usuarios", json={**datos, "jefe_id": None, "sede_id": mundo["med"]})
    assert r.status_code == 403
    r = mx.post("/api/usuarios", json={**datos, "jefe_id": None, "turno_id": mundo["turno_med"]})
    assert r.status_code == 422 and "otra sede" in r.json()["detail"]


def test_cambio_de_sede_solo_super_administrador(mundo):
    mx = entrar("admin@empresa.com", "Admin123")
    ana = next(u for u in mx.get("/api/usuarios").json() if u["nombre"] == "Ana López")
    cuerpo = {k: ana[k] for k in ("numero_empleado", "nombre", "email", "rol", "fecha_ingreso", "jefe_id", "turno_id", "es_jefe", "activo")}
    assert mx.put(f"/api/usuarios/{ana['id']}", json={**cuerpo, "sede_id": mundo["med"]}).status_code == 403

    su = entrar("super.sedes@o-tek.com", "Clave12345")
    r = su.put(f"/api/usuarios/{ana['id']}", json={**cuerpo, "sede_id": mundo["med"]})
    assert r.status_code == 200, r.text
    movida = r.json()
    assert movida["sede_nombre"] == "O-Tek Colombia - Medellín"
    assert movida["jefe_id"] is None and movida["turno_id"] is None  # eran de la sede anterior
    # Ya no es de su sede: no aparece en su lista ni la puede editar
    assert all(u["id"] != ana["id"] for u in mx.get("/api/usuarios").json())
    assert mx.put(f"/api/usuarios/{ana['id']}", json=cuerpo).status_code == 404
    # Se regresa a México para no afectar otras pruebas
    r = su.put(f"/api/usuarios/{ana['id']}", json={**cuerpo, "sede_id": mundo["mx"]})
    assert r.status_code == 200


def test_administrador_con_varias_sedes_y_selector(mundo):
    su = entrar("super.sedes@o-tek.com", "Clave12345")
    with SessionLocal() as db:
        laura = db.query(Usuario).filter(Usuario.email == "laura@empresa.com").one()
        # Laura pasa a ser GH: solo administra su sede, aunque se le asignen otras
        laura.rol = "admin"
        db.commit()
        lid = laura.id
    base = su.get(f"/api/usuarios/{lid}").json()
    cuerpo = {k: base[k] for k in ("numero_empleado", "nombre", "email", "rol", "fecha_ingreso", "jefe_id", "turno_id", "es_jefe", "activo")}
    r = su.put(f"/api/usuarios/{lid}", json={**cuerpo, "sedes_admin": [mundo["med"]]})
    assert r.status_code == 200 and r.json()["sedes_admin"] == []
    assert "Empleado Medellín" not in {u["nombre"] for u in entrar("laura@empresa.com", "Cambiar123").get("/api/usuarios").json()}
    # Como Gerencia GH, el super administrador le asigna México y Medellín
    r = su.put(f"/api/usuarios/{lid}", json={**cuerpo, "rol": "gerencia_gh", "sedes_admin": [mundo["med"]]})
    assert r.status_code == 200 and r.json()["sedes_admin"] == [mundo["med"]]

    laura = entrar("laura@empresa.com", "Cambiar123")
    nombres = {u["nombre"] for u in laura.get("/api/usuarios").json()}
    assert {"Ana López", "Empleado Medellín"} <= nombres
    assert len(laura.get("/api/auth/me").json()["sedes"]) == 2
    # Con el selector solo ve la sede elegida
    solo_med = entrar("laura@empresa.com", "Cambiar123", sede=mundo["med"])
    assert "Ana López" not in {u["nombre"] for u in solo_med.get("/api/usuarios").json()}
    # Los nombres de turno son únicos por sede: "Oficina" existe en México y se puede crear en Medellín
    r = solo_med.post("/api/turnos", json={"nombre": "Oficina", "hora_entrada": "08:00", "hora_salida": "17:00", "horas_jornada": 8})
    assert r.status_code == 201 and r.json()["sede_id"] == mundo["med"]
    # Una sede que no administra no se puede elegir: el encabezado se ignora
    with SessionLocal() as db:
        db.query(AdminSede).filter(AdminSede.usuario_id == lid).delete()
        db.get(Usuario, lid).rol = "oficina"
        db.commit()
    otra = entrar("laura@empresa.com", "Cambiar123", sede=mundo["med"])
    assert all(t["sede_id"] == mundo["mx"] for t in otra.get("/api/turnos").json())
    assert all(f["sede_id"] == mundo["mx"] for f in otra.get("/api/festivos").json())


def test_sedes_solo_las_administra_el_super_administrador(mundo):
    mx = entrar("admin@empresa.com", "Admin123")
    assert mx.post("/api/sedes", json={"nombre": "Otra"}).status_code == 403
    assert [s["nombre"] for s in mx.get("/api/sedes").json()] == ["O-tek México"]
    su = entrar("super.sedes@o-tek.com", "Clave12345")
    assert su.post("/api/sedes", json={"nombre": "Zona mala", "zona_horaria": "Marte/Base"}).status_code == 422
    r = su.post("/api/sedes", json={"nombre": "O-Tek Colombia - Cartagena", "ubicacion_microsoft": "O-Tek Colombia - Cartagena",
                                    "zona_horaria": "America/Bogota"})
    assert r.status_code == 201, r.text
    assert su.post("/api/sedes", json={"nombre": "O-Tek Colombia - Cartagena"}).status_code == 409
    # No se desactiva una sede con empleados activos
    assert su.put(f"/api/sedes/{mundo['med']}", json={"nombre": "O-Tek Colombia - Medellín",
                                                       "zona_horaria": "America/Bogota", "activa": False}).status_code == 400
