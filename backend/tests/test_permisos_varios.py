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


def test_lote_se_aprueba_y_rechaza_una_sola_vez():
    ana, admin = entrar("ana@empresa.com"), entrar("admin@empresa.com", "Admin123")
    base = {"tipo": "salida_temprana", "hora_inicio": "16:00", "hora_fin": "17:00", "motivo": "Curso por las tardes",
            "tipo_nomina": "reposicion", "enviar": True, "firma": FIRMA}
    lunes = lunes_en(14)
    _borrar("ana@empresa.com", lunes, lunes + timedelta(days=6))
    r = ana.post("/api/permisos/varios", json={**base, "fecha": str(lunes), "fecha_fin": str(lunes + timedelta(days=4))})
    assert r.status_code == 201, r.text
    creados = r.json()
    n = len(creados)
    assert n >= 2
    principal = min(creados, key=lambda p: p["fecha"])
    assert all(p["lote"] == principal["id"] for p in creados)
    assert len(ana.get(f"/api/permisos/{principal['id']}").json()["lote_fechas"]) == n

    # Una sola validación (del jefe) deja validados todos los días
    assert admin.post(f"/api/permisos/{principal['id']}/validar", json={}).status_code == 200
    estados = {ana.get(f"/api/permisos/{p['id']}").json()["estado"] for p in creados}
    assert estados == {"validado"}

    # Un solo rechazo (desde cualquier día) rechaza todo el lote con el mismo motivo
    otro = lunes_en(15)
    _borrar("ana@empresa.com", otro, otro + timedelta(days=6))
    creados = ana.post("/api/permisos/varios", json={**base, "fecha": str(otro), "fecha_fin": str(otro + timedelta(days=4))}).json()
    ultimo = max(creados, key=lambda p: p["fecha"])
    assert admin.post(f"/api/permisos/{ultimo['id']}/rechazar", json={"motivo": "Cierre de mes"}).status_code == 200
    for p in creados:
        d = ana.get(f"/api/permisos/{p['id']}").json()
        assert d["estado"] == "rechazado" and d["motivo_rechazo"] == "Cierre de mes"

    # Un permiso de un solo día no forma lote
    solo = ana.post("/api/permisos/varios", json={**base, "fecha": str(otro + timedelta(days=7)),
                                                  "fecha_fin": str(otro + timedelta(days=7))})
    if solo.status_code == 201:
        assert solo.json()[0]["lote"] is None
    _borrar("ana@empresa.com", lunes, otro + timedelta(days=8))


def test_lote_por_teams_solo_el_principal_lleva_tarjeta():
    from app import sharepoint
    from app.database import SessionLocal
    ana = entrar("ana@empresa.com")
    lunes = lunes_en(17)
    _borrar("ana@empresa.com", lunes, lunes + timedelta(days=6))
    creados = ana.post("/api/permisos/varios", json={
        "tipo": "llegada_tarde", "fecha": str(lunes), "fecha_fin": str(lunes + timedelta(days=4)), "hora_inicio": "08:00",
        "hora_fin": "09:00", "motivo": "Cita", "tipo_nomina": "reposicion", "enviar": True, "firma": FIRMA}).json()
    with SessionLocal() as db:
        regs = sorted((db.get(Permiso, p["id"]) for p in creados), key=lambda p: p.fecha)
        datos = [sharepoint.datos_registro("permisos", r) for r in regs]
        # El principal lleva el correo del jefe y todas las fechas; los demás no piden aprobación aparte
        assert datos[0]["correo_jefe"] and "Aplica a" in datos[0]["motivo"]
        assert all(d["correo_jefe"] is None for d in datos[1:])
    _borrar("ana@empresa.com", lunes, lunes + timedelta(days=6))
