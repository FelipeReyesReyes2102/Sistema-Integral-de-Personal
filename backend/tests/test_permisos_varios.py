"""Permiso por horas en varios días: uno por cada día laboral del rango, todo o nada."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Permiso, Usuario
from tests.test_home_office import FIRMA, entrar, lunes_en


def _borrar(email, desde, hasta):
    with SessionLocal() as db:
        uid = db.query(Usuario.id).filter(Usuario.email == email).scalar()
        db.query(Permiso).filter(Permiso.usuario_id == uid, Permiso.fecha >= desde, Permiso.fecha <= hasta).delete()
        db.commit()


def test_permiso_llegada_tarde_varios_dias():
    ana = entrar("ana@empresa.com")
    lunes = lunes_en(11)
    domingo = lunes + timedelta(days=6)
    _borrar("ana@empresa.com", lunes, domingo)
    festivos = {f["fecha"] for f in ana.get(f"/api/festivos?anio={lunes.year}").json()}
    esperados = [str(lunes + timedelta(days=i)) for i in range(5) if str(lunes + timedelta(days=i)) not in festivos]
    datos = {"tipo": "llegada_tarde", "fecha": str(lunes), "fecha_fin": str(domingo), "hora_inicio": "08:30",
             "hora_fin": "09:30", "motivo": "Terapia por las mañanas", "tipo_nomina": "reposicion",
             "enviar": True, "firma": FIRMA}
    r = ana.post("/api/permisos/varios", json=datos)
    assert r.status_code == 201, r.text
    creados = r.json()
    # Uno por día laboral (sin fin de semana ni festivos), mismo horario, enviados al jefe
    assert sorted(p["fecha"] for p in creados) == esperados
    assert all(p["horas"] == 1 and p["estado"] == "solicitado" and p["fecha_fin"] is None for p in creados)

    # Todo o nada: si un día ya no es válido (p. ej. excede la jornada) no se crea ninguno
    otro = lunes_en(12)
    _borrar("ana@empresa.com", otro, otro + timedelta(days=6))
    r = ana.post("/api/permisos/varios", json={**datos, "fecha": str(otro), "fecha_fin": str(otro + timedelta(days=4)),
                                               "hora_inicio": "00:00", "hora_fin": "23:00"})
    assert r.status_code == 422 and "/" in r.text
    with SessionLocal() as db:
        uid = db.query(Usuario.id).filter(Usuario.email == "ana@empresa.com").scalar()
        assert db.query(Permiso).filter(Permiso.usuario_id == uid, Permiso.fecha >= otro,
                                        Permiso.fecha <= otro + timedelta(days=6)).count() == 0
    # Límites del rango
    assert ana.post("/api/permisos/varios", json={**datos, "fecha_fin": str(lunes + timedelta(days=40))}).status_code == 422
    assert ana.post("/api/permisos/varios", json={**datos, "tipo": "home_office"}).status_code == 422
    _borrar("ana@empresa.com", lunes, domingo)
