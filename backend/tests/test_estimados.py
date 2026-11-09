"""Cumpleaños y aniversarios: los del personal de la sede se ven en el calendario; cada quien puede ocultarlos."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Usuario
from app.seed import main as seed
from tests.test_consultas import entrar

seed()
ANIO = date.today().year


def _fechas(email, nacimiento, ingreso=None):
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.email == email).one()
        u.fecha_nacimiento = nacimiento
        if ingreso:
            u.fecha_ingreso = ingreso
        db.commit()
        return u.id


def _preferencias_por_defecto():
    with SessionLocal() as db:
        for u in db.query(Usuario).filter(Usuario.email.in_(["ana@empresa.com", "laura@empresa.com"])):
            u.ver_cumpleanos = u.ver_aniversarios = True
        db.commit()


def test_cumpleanos_y_aniversarios_publicos_con_opcion_de_ocultar():
    _preferencias_por_defecto()
    laura_id = _fechas("laura@empresa.com", date(1988, 5, 14))
    _fechas("ana@empresa.com", date(1992, 9, 3))
    ana = entrar("ana@empresa.com")

    cal = ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"]
    de_laura = {c["tipo"]: c for c in cal if c["usuario_id"] == laura_id}
    assert de_laura["cumpleanos"]["fecha"] == f"{ANIO}-05-14" and "1988" not in str(de_laura["cumpleanos"])
    assert de_laura["aniversario"]["anios"] >= 1
    assert any(c["propio"] for c in cal)

    # Ocultar aniversarios: siguen los cumpleaños
    assert ana.put("/api/estimados/preferencias", json={"ver_cumpleanos": True, "ver_aniversarios": False}).status_code == 200
    tipos = {c["tipo"] for c in ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"] if c["usuario_id"] == laura_id}
    assert tipos == {"cumpleanos"} and ana.get("/api/auth/me").json()["ver_aniversarios"] is False

    # Ocultar todo: solo queda el propio
    ana.put("/api/estimados/preferencias", json={"ver_cumpleanos": False, "ver_aniversarios": False})
    cal = ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"]
    assert cal and all(c["propio"] for c in cal)
    _preferencias_por_defecto()


def test_proximos_cumpleanos():
    _preferencias_por_defecto()
    pronto = date.today() + timedelta(days=5)
    laura_id = _fechas("laura@empresa.com", date(1988, pronto.month, min(pronto.day, 28)))
    datos = entrar("ana@empresa.com").get("/api/estimados").json()
    assert datos["preferencias"] == {"ver_cumpleanos": True, "ver_aniversarios": True}
    if pronto.day <= 28:
        assert any(e["usuario_id"] == laura_id and e["tipo"] == "cumpleanos" for e in datos["proximos"])
