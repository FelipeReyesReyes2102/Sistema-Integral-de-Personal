"""Cumpleaños y aniversarios: solo se ven en mi calendario si la otra persona aceptó mi solicitud."""
from datetime import date

from app.database import SessionLocal
from app.models import ContactoCalendario, Usuario
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


def _limpiar():
    with SessionLocal() as db:
        db.query(ContactoCalendario).delete()
        for u in db.query(Usuario).filter(Usuario.email.in_(["ana@empresa.com", "laura@empresa.com"])):
            u.ver_cumpleanos = u.ver_aniversarios = True
        db.commit()


def test_cumpleanos_y_aniversarios_con_autorizacion():
    _limpiar()
    laura_id = _fechas("laura@empresa.com", date(1988, 5, 14))
    _fechas("ana@empresa.com", date(1992, 9, 3))
    ana, laura = entrar("ana@empresa.com"), entrar("laura@empresa.com")

    cal = ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"]
    assert [c["nombre"] for c in cal if not c["propio"]] == [] and any(c["propio"] for c in cal)  # solo el propio

    # Ana pide ver el cumpleaños y aniversario de Laura
    enc = next(p for p in ana.get("/api/estimados/buscar", params={"q": "laura martinez"}).json() if p["id"] == laura_id)
    assert enc["estado"] is None
    r = ana.post("/api/estimados", json={"persona_id": laura_id})
    assert r.status_code == 201 and r.json()["estado"] == "pendiente"
    assert ana.post("/api/estimados", json={"persona_id": laura_id}).status_code == 409
    assert laura.get("/api/pendientes").json()["estimados"] == 1
    cid = laura.get("/api/estimados").json()["recibidas"][0]["id"]
    assert ana.post(f"/api/estimados/{cid}/aceptar").status_code == 404  # solo la persona responde

    # Laura la rechaza: Ana sigue sin verla; puede volver a pedirla y Laura acepta
    assert laura.post(f"/api/estimados/{cid}/rechazar").json()["estado"] == "rechazada"
    assert not [c for c in ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"] if c["usuario_id"] == laura_id]
    assert ana.post("/api/estimados", json={"persona_id": laura_id}).json()["estado"] == "pendiente"
    assert laura.post(f"/api/estimados/{cid}/aceptar").json()["estado"] == "aceptada"
    cal = ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"]
    de_laura = {c["tipo"]: c for c in cal if c["usuario_id"] == laura_id}
    assert de_laura["cumpleanos"]["fecha"] == f"{ANIO}-05-14" and "aniversario" in de_laura
    assert de_laura["aniversario"]["anios"] >= 1
    assert laura.get("/api/estimados").json()["me_ven"][0]["persona"]["nombre"].startswith("Ana")

    # Preferencias: Ana deja de ver aniversarios
    assert ana.put("/api/estimados/preferencias", json={"ver_cumpleanos": True, "ver_aniversarios": False}).status_code == 200
    tipos = {c["tipo"] for c in ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"] if c["usuario_id"] == laura_id}
    assert tipos == {"cumpleanos"} and ana.get("/api/auth/me").json()["ver_aniversarios"] is False

    # Laura le quita el acceso
    assert laura.delete(f"/api/estimados/{cid}").status_code == 204
    assert not [c for c in ana.get(f"/api/calendario?anio={ANIO}").json()["cumpleanos"] if c["usuario_id"] == laura_id]
    _limpiar()
