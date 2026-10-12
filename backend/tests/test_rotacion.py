"""Rotación de turnos: alternancia por periodos, sincronización, turno único al desactivar y aviso de los viernes."""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import correo, rotacion
from app.database import SessionLocal
from app.main import app
from app.models import Grupo, Turno, Usuario
from app.seed import main as seed

ENVIADOS: list = []


class SMTPFalso:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        ENVIADOS.append(msg)


def entrar(usuario, pwd="Cambiar123"):
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": usuario, "password": pwd}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


@pytest.fixture
def ids():
    seed()
    with SessionLocal() as db:
        t = {x.nombre: x.id for x in db.query(Turno)}
        g = {x.nombre: x.id for x in db.query(Grupo)}
    yield t, g
    with SessionLocal() as db:  # dejar todo como estaba
        cfg = rotacion.config(db)
        cfg.activo, cfg.aviso_activo, cfg.ultimo_aviso = False, False, None
        for u in db.query(Usuario):
            if u.email_personal == "carlos@empresa.com":
                u.turno_id = t["Día"]
            if u.email_personal == "maria@empresa.com":
                u.turno_id = t["Noche"]
        db.commit()
        correo.guardar(db, {k: None for k in correo.CLAVES}, None)


def config_activa(t, g, **extra):
    lunes = date.today() - timedelta(days=date.today().weekday())
    datos = {"activo": True, "fecha_inicio": str(lunes), "semanas": 1, "turnos_orden": [t["Día"], t["Noche"]],
             "turno_unico_id": t["Día"], "aviso_activo": False, "aviso_hora": 12,
             "grupos": [{"grupo_id": g["Grupo A"], "en_rotacion": True, "turno_inicial_id": t["Día"]},
                        {"grupo_id": g["Grupo B"], "en_rotacion": True, "turno_inicial_id": t["Noche"]}]}
    datos.update(extra)
    return datos


def test_rotacion_alterna_y_sincroniza(ids):
    t, g = ids
    admin = entrar("admin@empresa.com", "Admin123")
    r = admin.put("/api/rotacion", json=config_activa(t, g))
    assert r.status_code == 200, r.text
    est = r.json()
    # Vista previa: A y B intercambian turno cada semana
    v = est["vista_previa"]
    assert v[0]["grupos"][str(g["Grupo A"])] == "Día" and v[0]["grupos"][str(g["Grupo B"])] == "Noche"
    assert v[1]["grupos"][str(g["Grupo A"])] == "Noche" and v[1]["grupos"][str(g["Grupo B"])] == "Día"

    # "Mi turno" de Carlos (Grupo A): esta semana Día, la próxima Noche
    carlos = entrar("carlos@empresa.com")
    mt = carlos.get("/api/turnos/mi-turno").json()
    assert mt["rotacion_activa"] and mt["actual"]["nombre"] == "Día"
    assert mt["siguiente_semana"]["turno"]["nombre"] == "Noche" and mt["semanas"][2]["turno"]["nombre"] == "Día"
    assert mt["proximo_cambio"] == str(date.today() - timedelta(days=date.today().weekday()) + timedelta(weeks=1))

    # Sincronización: a la semana siguiente Carlos queda en Noche
    with SessionLocal() as db:
        rotacion.sincronizar(db, date.today() + timedelta(weeks=1))
        assert db.query(Usuario).filter(Usuario.email_personal == "carlos@empresa.com").one().turno.nombre == "Noche"
        assert db.query(Usuario).filter(Usuario.email_personal == "maria@empresa.com").one().turno.nombre == "Día"


def test_desactivar_deja_a_todos_en_un_solo_turno(ids):
    t, g = ids
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/rotacion", json=config_activa(t, g))
    r = admin.put("/api/rotacion", json=config_activa(t, g, activo=False, turno_unico_id=t["Día"]))
    assert r.status_code == 200 and not r.json()["activo"]
    with SessionLocal() as db:
        turnos = {u.turno.nombre for u in db.query(Usuario).filter(Usuario.grupo_id.in_([g["Grupo A"], g["Grupo B"]]))}
    assert turnos == {"Día"}
    assert entrar("maria@empresa.com").get("/api/turnos/mi-turno").json()["rotacion_activa"] is False


def test_validaciones_y_permisos(ids):
    t, g = ids
    admin = entrar("admin@empresa.com", "Admin123")
    r = admin.put("/api/rotacion", json=config_activa(t, g, turnos_orden=[t["Día"]]))
    assert r.status_code == 422 and "dos turnos" in r.text
    r = admin.put("/api/rotacion", json=config_activa(t, g, fecha_inicio=None))
    assert r.status_code == 422 and "fecha" in r.text
    r = admin.put("/api/rotacion", json=config_activa(t, g, activo=False, turno_unico_id=None))
    assert r.status_code == 422 and "turno único" in r.text
    assert entrar("ana@empresa.com").get("/api/rotacion").status_code == 403


def test_aviso_de_los_viernes(ids, monkeypatch):
    t, g = ids
    monkeypatch.setattr(correo.smtplib, "SMTP", SMTPFalso)
    ENVIADOS.clear()
    with SessionLocal() as db:
        correo.guardar(db, {"CORREO_REMITENTE": "avisos@o-tek.com", "CORREO_SMTP_HOST": "smtp.o-tek.com"}, None)
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/rotacion", json=config_activa(t, g, aviso_activo=True, aviso_hora=12))

    viernes = date.today() + timedelta(days=(4 - date.today().weekday()) % 7)
    rotacion.tarea_programada(datetime.combine(viernes, datetime.min.time()).replace(hour=9))   # antes de la hora
    assert ENVIADOS == []
    rotacion.tarea_programada(datetime.combine(viernes, datetime.min.time()).replace(hour=13))
    destinatarios = sorted(m["To"] for m in ENVIADOS)
    assert destinatarios == ["carlos@empresa.com", "maria@empresa.com"]
    assert all("próxima semana" in m["Subject"] for m in ENVIADOS)
    cuerpo = next(m for m in ENVIADOS if m["To"] == "carlos@empresa.com").get_body(("plain",)).get_content()
    assert "Grupo A" in cuerpo and "Próxima semana" in cuerpo
    rotacion.tarea_programada(datetime.combine(viernes, datetime.min.time()).replace(hour=15))  # no se duplica
    assert len(ENVIADOS) == 2
    # Envío manual desde la pantalla
    assert admin.post("/api/rotacion/avisos").json()["enviados"] == 2
