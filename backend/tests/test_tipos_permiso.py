"""Tipos de permiso configurables por sede, con límite por mes, por año o sin límite."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.seed import main as seed
from tests.test_api import FIRMA, login

seed()


def _empleado(email):
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.email == email).first()
        if not u:
            jefe = db.query(Usuario).filter(Usuario.email == "laura@empresa.com").first()
            u = Usuario(numero_empleado=email.split("@")[0], nombre="Tipos " + email.split("@")[0], email=email,
                        rol="oficina", password_hash=hash_password("Cambiar123"),
                        fecha_ingreso=date.today() - timedelta(days=800), sede_id=sede_principal(db).id,
                        jefe_id=jefe.id if jefe else None)
            db.add(u)
            db.commit()
    return login(email, "Cambiar123")


def _habil(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def test_tipo_por_dias_con_limite_anual():
    adm = login("admin@empresa.com", "Admin123")
    base = adm.get("/api/tipos-permiso").json()
    assert {t["clave"] for t in base if t["base"]} == {"llegada_tarde", "salida_temprana", "salida_intermedia", "home_office"}
    r = adm.post("/api/tipos-permiso", json={"nombre": "Día de cumpleaños", "modalidad": "dias", "pide_nomina": False,
                                             "limite_cantidad": 1, "limite_unidad": "dias", "limite_periodo": "anio",
                                             "max_dias_solicitud": 1})
    assert r.status_code == 201, r.text
    tipo = r.json()
    assert tipo["clave"] == "dia_de_cumpleanos" and not tipo["base"]
    assert adm.post("/api/tipos-permiso", json={"nombre": "día de cumpleaños"}).status_code == 409
    assert "permisos_tipos" in adm.get("/api/politica").json()

    emp = _empleado("cumple.tipos@empresa.com")
    assert any(t["clave"] == tipo["clave"] for t in emp.get("/api/politica").json()["permisos_tipos"])
    d = _habil(date(date.today().year + 1, 3, 2))
    r = emp.post("/api/permisos", json={"tipo": tipo["clave"], "fecha": str(d), "fecha_fin": str(d), "motivo": "Cumpleaños",
                                        "enviar": True, "firma": FIRMA})
    assert r.status_code == 201, r.text
    assert r.json()["tipo_nombre"] == "Día de cumpleaños" and r.json()["por_dias"] and r.json()["dias"] == 1
    uso = emp.get("/api/permisos/uso", params={"tipo": tipo["clave"], "fecha": str(d)}).json()
    assert uso["limite"] == 1 and uso["usado"] == 1 and uso["periodo"] == "anio"
    otro = _habil(d + timedelta(days=30))
    r = emp.post("/api/permisos", json={"tipo": tipo["clave"], "fecha": str(otro), "fecha_fin": str(otro), "motivo": "Otra vez"})
    assert r.status_code == 422 and "1 día(s) por año" in r.json()["detail"], r.text
    # Al año siguiente vuelve a estar disponible
    sig = _habil(date(d.year + 1, 3, 2))
    assert emp.post("/api/permisos", json={"tipo": tipo["clave"], "fecha": str(sig), "fecha_fin": str(sig),
                                           "motivo": "Siguiente"}).status_code == 201
    # No se borra con permisos; desactivado ya no se puede pedir
    assert adm.delete(f"/api/tipos-permiso/{tipo['id']}").status_code == 400
    r = adm.put(f"/api/tipos-permiso/{tipo['id']}", json={**{k: tipo[k] for k in (
        "nombre", "modalidad", "pide_nomina", "limite_cantidad", "limite_unidad", "limite_periodo", "max_dias_solicitud",
        "color")}, "activo": False})
    assert r.status_code == 200 and not r.json()["activo"]
    r = emp.post("/api/permisos", json={"tipo": tipo["clave"], "fecha": str(sig + timedelta(days=60)), "motivo": "x"})
    assert r.status_code == 422 and "no está habilitado" in r.json()["detail"]


def test_tipo_por_horas_con_limite_mensual_y_tipos_base():
    adm = login("admin@empresa.com", "Admin123")
    r = adm.post("/api/tipos-permiso", json={"nombre": "Trámite personal", "modalidad": "horas", "pide_nomina": True,
                                             "limite_cantidad": 3, "limite_unidad": "horas", "limite_periodo": "mes"})
    assert r.status_code == 201, r.text
    clave = r.json()["clave"]
    assert adm.post("/api/tipos-permiso", json={"nombre": "Raro", "modalidad": "dias", "limite_unidad": "horas",
                                                "limite_cantidad": 2}).status_code == 422
    emp = _empleado("tramite.tipos@empresa.com")
    d = _habil(date(date.today().year + 1, 5, 4))
    datos = {"tipo": clave, "fecha": str(d), "hora_inicio": "09:00", "hora_fin": "11:00", "motivo": "Banco"}
    assert emp.post("/api/permisos", json=datos).status_code == 201
    r = emp.post("/api/permisos", json={**datos, "fecha": str(_habil(d + timedelta(days=1))), "hora_fin": "11:30"})
    assert r.status_code == 422 and "3 h por mes" in r.json()["detail"] and "te quedan 1" in r.json()["detail"], r.text
    # Para enviar pide el tipo de nómina
    r = emp.post("/api/permisos", json={**datos, "fecha": str(_habil(d + timedelta(days=1))), "hora_fin": "10:00",
                                        "enviar": True, "firma": FIRMA})
    assert r.status_code == 422 and "nómina" in r.json()["detail"]
    # Los tipos base no se eliminan
    ho = next(t for t in adm.get("/api/tipos-permiso").json() if t["clave"] == "home_office")
    assert adm.delete(f"/api/tipos-permiso/{ho['id']}").status_code == 400
    sin_uso = adm.post("/api/tipos-permiso", json={"nombre": "Temporal"}).json()
    assert adm.delete(f"/api/tipos-permiso/{sin_uso['id']}").status_code == 204
