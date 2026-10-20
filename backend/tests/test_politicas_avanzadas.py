"""Generación de días, descuento por jornada, vacaciones por horas, aprobación jefe + GH y planeación con saldo negativo."""
from datetime import date, timedelta

from app import reglas
from app.database import SessionLocal
from app.models import PeriodoVacaciones, Sede, TipoJornada, Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.services import saldo_periodo, sincronizar_periodos
from app.seed import main as seed
from tests.test_api import FIRMA, login

seed()


def test_generacion_calendario_y_mensual():
    ingreso = date(2024, 4, 10)
    cal = reglas.periodos_generados(ingreso, date(2026, 6, 1), "calendario", 18)
    assert [(p.numero, p.fecha_inicio) for p in cal] == [(1, date(2025, 1, 1)), (2, date(2026, 1, 1))]
    assert cal[0].fraccion == round(9 / 12, 4) and cal[1].fraccion == 1.0  # abril (antes del 16) a diciembre
    men = reglas.periodos_generados(ingreso, date(2025, 7, 15), "mensual", 18)
    assert [(p.numero, p.fraccion) for p in men] == [(1, 1.0), (2, round(3 / 12, 4))]  # año 2: 3 meses cumplidos
    assert men[1].fecha_vencimiento == date(2027, 10, 9)  # 18 meses después de completarse
    ani = reglas.periodos_generados(ingreso, date(2025, 7, 15), "aniversario", 18)
    assert [p.numero for p in ani] == [1]


def _usuario(nombre, email, ingreso, rol="oficina"):
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.email == email).first()
        if not u:
            u = Usuario(numero_empleado=email.split("@")[0], nombre=nombre, email=email, rol=rol,
                        password_hash=hash_password("Cambiar123"), fecha_ingreso=ingreso, sede_id=sede_principal(db).id)
            db.add(u)
            db.commit()
        return u.id


def test_descuento_por_jornada_y_vacaciones_por_horas():
    uid = _usuario("Pedro Horas", "pedro.horas@empresa.com", date.today() - timedelta(days=400))
    with SessionLocal() as db:
        sede = sede_principal(db)
        j = TipoJornada(sede_id=sede.id, nombre="Planta 12 h por horas", horas_dia=12, bloque_minimo=1,
                        usa_ciclo_grupo=False, descuento="dias", por_horas=True, minimo_horas=2)
        db.add(j)
        db.commit()
        u = db.get(Usuario, uid)
        u.tipo_jornada_id = j.id
        u.jefe_id = db.query(Usuario).filter(Usuario.email_personal == "laura@empresa.com").first().id             if db.query(Usuario).filter(Usuario.email_personal == "laura@empresa.com").first() else             db.query(Usuario).filter(Usuario.email == "laura@empresa.com").first().id
        db.commit()
        p = sincronizar_periodos(db, u)[0]
        # "dias": cada día de la tabla es un día de 12 h (aunque la sede use equivalencia en horas)
        assert p.horas_otorgadas == 12 * 12 and saldo_periodo(db, p).dias_disponible == 12
        jid, pid = j.id, p.id
    pedro = login("pedro.horas@empresa.com", "Cambiar123")
    d = date.today() + timedelta(days=10)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    base = {"fecha_inicio": str(d), "fecha_fin": str(d)}
    c = pedro.post("/api/vacaciones/calcular", json={**base, "horas": 4}).json()
    assert c["permite_horas"] and c["horas_dia"] == 12 and not c["errores"], c
    assert "mínimo es 2 h" in " ".join(pedro.post("/api/vacaciones/calcular", json={**base, "horas": 1}).json()["errores"])
    assert "día completo" in " ".join(pedro.post("/api/vacaciones/calcular", json={**base, "horas": 12}).json()["errores"])
    r = pedro.post("/api/vacaciones", json={**base, "horas": 4, "enviar": True, "firma": FIRMA})
    assert r.status_code == 201, r.text
    assert r.json()["por_horas"] and r.json()["horas"] == 4 and r.json()["dias_habiles"] == 0
    with SessionLocal() as db:
        assert saldo_periodo(db, db.get(PeriodoVacaciones, pid)).horas_disponible == 144 - 4
        db.get(TipoJornada, jid).por_horas = False
        db.commit()
    assert "no permite vacaciones por horas" in " ".join(
        pedro.post("/api/vacaciones/calcular", json={**base, "horas": 4}).json()["errores"])


def test_aprobacion_jefe_mas_gh():
    adm, laura, carlos = (login("admin@empresa.com", "Admin123"), login("laura@empresa.com", "Cambiar123"),
                          login("carlos@empresa.com", "Cambiar123"))
    pol = adm.get("/api/politica").json()
    campos = ("meses_vigencia", "equivalencia_horas", "dias_anticipacion", "tipos_permiso", "home_office_max_dias",
              "modulo_consultas", "modulo_cumpleanos", "generacion_dias", "aprobacion_gh_vacaciones", "aprobacion_gh_permisos")
    base = {k: pol[k] for k in campos}
    assert adm.put("/api/politica", json={**base, "aprobacion_gh_permisos": True}).status_code == 200
    d = date.today() + timedelta(days=12)
    r = carlos.post("/api/permisos", json={"tipo": "home_office", "fecha": str(d), "fecha_fin": str(d),
                                           "motivo": "Dos niveles", "firma": FIRMA, "enviar": True})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    antes = laura.get("/api/pendientes").json()["permisos"]
    p = laura.post(f"/api/permisos/{pid}/validar", json={}).json()
    assert p["estado"] == "solicitado" and p["falta_gh"] and p["aprobado_jefe_nombre"] == "Laura Martínez"
    assert laura.get("/api/pendientes").json()["permisos"] == antes - 1  # ya no es pendiente del jefe
    assert pid not in [x["id"] for x in laura.get("/api/permisos", params={"por_aprobar": True, "estado": "solicitado"}).json()]
    assert laura.post(f"/api/permisos/{pid}/validar", json={}).status_code == 400
    p = adm.post(f"/api/permisos/{pid}/validar", json={}).json()
    assert p["estado"] == "validado" and not p["falta_gh"]
    adm.post(f"/api/permisos/{pid}/cancelar")
    adm.put("/api/politica", json=base)
