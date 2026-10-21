"""Caseta: permisos validados del día y registro de retardos que valida el jefe inmediato (o GH)."""
from datetime import datetime, timedelta

from app import correo
from app.database import SessionLocal
from app.models import Permiso, Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.seed import main as seed
from tests.test_consultas import entrar

seed()


def _caseta():
    with SessionLocal() as db:
        if not db.query(Usuario).filter(Usuario.numero_empleado == "CAS-1").first():
            db.add(Usuario(numero_empleado="CAS-1", nombre="Guardia Caseta", email_personal="guardia@gmail.com", rol="caseta",
                           password_hash=hash_password("Cambiar123"), fecha_ingreso=datetime(2024, 1, 1).date(),
                           sede_id=sede_principal(db).id))
            db.commit()
    return entrar("guardia@gmail.com")


def _limpiar(*ids):
    with SessionLocal() as db:
        for i in ids:
            p = db.get(Permiso, i)
            if p:
                db.delete(p)
        db.commit()


def _despues(hhmm, minutos):
    return (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutos)).strftime("%H:%M")


def test_caseta_retardos_y_permisos_del_dia(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto)))
    cas = _caseta()
    assert "caseta:consultar" in cas.get("/api/auth/me").json()["permissions"]
    assert entrar("carlos@empresa.com").get("/api/caseta/hoy").status_code == 403

    # Buscar al empleado y registrar su retardo: va a su jefe inmediato
    carlos = next(e for e in cas.get("/api/caseta/empleados", params={"q": "perez"}).json() if e["nombre"] == "Carlos Pérez")
    assert carlos["entrada_hoy"] and carlos["jefe_nombre"] == "Laura Martínez"
    assert cas.post("/api/caseta/retardos", json={"usuario_id": carlos["id"], "hora_llegada": carlos["entrada_hoy"]}).status_code == 422
    llegada = _despues(carlos["entrada_hoy"], 25)
    r = cas.post("/api/caseta/retardos", json={"usuario_id": carlos["id"], "hora_llegada": llegada, "motivo": "Tráfico"})
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["estado"] == "solicitado" and ret["aprobador_nombre"] == "Laura Martínez" and ret["registrado_por"] == "Guardia Caseta"
    assert abs(ret["horas"] - 25 / 60) < 0.02
    assert any("laura@empresa.com" in d and "Retardo por validar" in a for d, a in enviados)
    assert cas.post("/api/caseta/retardos", json={"usuario_id": carlos["id"], "hora_llegada": llegada}).status_code == 409
    assert any(x["id"] == ret["id"] for x in cas.get("/api/caseta/retardos").json())

    # El jefe lo ve por aprobar, indica el tiempo en nómina y lo valida
    laura = entrar("laura@empresa.com")
    pend = laura.get("/api/permisos", params={"por_aprobar": True, "estado": "solicitado"}).json()
    fila = next(p for p in pend if p["id"] == ret["id"])
    assert fila["registrado_por_nombre"] == "Guardia Caseta" and fila["tipo"] == "llegada_tarde"
    v = laura.post(f"/api/permisos/{ret['id']}/validar", json={"tipo_nomina": "sin_goce"})
    assert v.status_code == 200 and v.json()["tipo_nomina"] == "sin_goce"
    hoy = cas.get("/api/caseta/hoy").json()
    assert any(x["id"] == ret["id"] and x["hora_fin"] == llegada for x in hoy["por_horas"])
    assert cas.post(f"/api/caseta/retardos/{ret['id']}/cancelar").status_code == 400  # ya revisado

    # "El jefe no está en planta": se envía a GH
    ana = next(e for e in cas.get("/api/caseta/empleados", params={"q": "ana"}).json() if e["nombre"].startswith("Ana"))
    if ana["entrada_hoy"]:
        r = cas.post("/api/caseta/retardos", json={"usuario_id": ana["id"], "hora_llegada": _despues(ana["entrada_hoy"], 10),
                                                   "enviar_gh": True})
        assert r.status_code == 201 and r.json()["va_a_gh"] is True
        assert any("admin@empresa.com" in d for d, _ in enviados)
        assert cas.post(f"/api/caseta/retardos/{r.json()['id']}/cancelar").json()["estado"] == "cancelado"
        _limpiar(r.json()["id"])
    _limpiar(ret["id"])


def test_medico_y_caseta_no_piden_vacaciones_ni_permisos():
    rango = {"fecha_inicio": "2030-03-04", "fecha_fin": "2030-03-05"}
    for c in (entrar("medico@empresa.com"), _caseta()):
        assert c.post("/api/vacaciones/calcular", json=rango).status_code == 403
        assert c.post("/api/vacaciones", json={**rango, "enviar": False}).status_code in (403, 422)
        r = c.post("/api/permisos", json={"tipo": "home_office", "fecha": "2030-03-04", "fecha_fin": "2030-03-04", "motivo": "x"})
        assert r.status_code == 403 and "no solicitan" in r.json()["detail"]
    # GH tampoco puede capturarles vacaciones, y caseta no les registra retardos
    adm = entrar("admin@empresa.com", "Admin123")
    with SessionLocal() as db:
        medico_id = db.query(Usuario).filter(Usuario.email == "medico@empresa.com").one().id
    assert adm.post("/api/vacaciones/calcular", json={**rango, "usuario_id": medico_id}).status_code == 403
    nombres = [e["nombre"] for e in _caseta().get("/api/caseta/empleados", params={"q": "patricia"}).json()]
    assert "Dra. Patricia Ruiz" not in nombres
    assert _caseta().post("/api/caseta/retardos", json={"usuario_id": medico_id, "hora_llegada": "23:00"}).status_code == 422


def test_super_administrador_ve_todas_las_pestanas():
    from tests.test_sharepoint import super_login
    su = super_login()
    permisos = su.get("/api/auth/me").json()["permissions"]
    assert {"consultas:registrar", "caseta:consultar", "usuarios:superadmin", "solicitudes:aprobar"} <= set(permisos)
    for ruta in ("/api/consultas/pacientes", "/api/consultas/bitacora", "/api/consultas?todos=true", "/api/caseta/hoy",
                 "/api/caseta/retardos", "/api/incapacidades?todos=true", "/api/bitacora?seccion=configuracion", "/api/pendientes"):
        assert su.get(ruta).status_code == 200, ruta
