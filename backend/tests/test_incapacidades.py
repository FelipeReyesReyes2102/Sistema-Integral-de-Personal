"""Datos de contacto del usuario, permiso de consultas para no médicos e incapacidades validadas por el jefe."""
from datetime import date, timedelta

from app import correo
from app.database import SessionLocal
from app.models import ConsultaMedica, NotificacionCorreo
from app.seed import main as seed
from tests.test_consultas import entrar

seed()
HOY = date.today()


def _usuario(adm, email):
    u = next(x for x in adm.get("/api/usuarios").json() if (x["email"] or x["email_personal"]) == email)
    return adm.get(f"/api/usuarios/{u['id']}").json()


def _guardar(adm, u, **cambios):
    campos = ("numero_empleado", "nombre", "sede_id", "tipo_jornada_id", "email", "email_personal", "rol", "fecha_ingreso",
              "fecha_nacimiento", "puesto", "departamento", "turno_id", "grupo_id", "jefe_id", "es_jefe", "activo",
              "puede_consultas", "direccion", "telefono", "contacto_nombre", "contacto_telefono")
    return adm.put(f"/api/usuarios/{u['id']}", json={**{k: u.get(k) for k in campos}, **cambios})


def test_contacto_y_permiso_de_consultas(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto)))
    adm = entrar("admin@empresa.com", "Admin123")
    ana = _usuario(adm, "ana@empresa.com")
    r = _guardar(adm, ana, telefono="abc")
    assert r.status_code == 422 and "teléfono" in r.json()["detail"]
    r = _guardar(adm, ana, direccion="Av. Reforma 100, CDMX", telefono="55 1234 5678", contacto_nombre="Pedro (hermano)",
                 contacto_telefono="+52 55 8765 4321", puede_consultas=True)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["direccion"] == "Av. Reforma 100, CDMX" and d["contacto_telefono"] == "+52 55 8765 4321" and d["puede_consultas"]

    # Ana (no es médico) ya puede registrar consultas con incapacidad
    ana_c = entrar("ana@empresa.com")
    assert "consultas:registrar" in ana_c.get("/api/auth/me").json()["permissions"]
    carlos = next(p for p in ana_c.get("/api/consultas/pacientes?q=Carlos").json() if p["nombre"] == "Carlos Pérez")
    inicio = HOY + timedelta(days=1)
    datos = {"paciente_id": carlos["id"], "fecha": str(HOY), "hora_inicio": "09:00", "hora_fin": "09:30",
             "sintomas": "Fiebre alta", "diagnostico": "Infección respiratoria", "resultado": "envia_casa",
             "incapacidad": {"fecha_inicio": str(inicio), "fecha_fin": str(inicio + timedelta(days=2)),
                             "tipo": "enfermedad_general", "folio": "IMSS-123", "observaciones": "Reposo en casa"}}
    assert ana_c.post("/api/consultas", json={**datos, "incapacidad": {**datos["incapacidad"], "fecha_fin": str(HOY)}}).status_code == 422
    r = ana_c.post("/api/consultas", json=datos)
    assert r.status_code == 201, r.text
    consulta = r.json()
    inc = consulta["incapacidad"]
    assert inc["dias"] == 3 and inc["estado"] == "solicitado" and inc["aprobador_nombre"] == "Laura Martínez"
    assert any("laura@empresa.com" in dest and "por validar" in asunto for dest, asunto in enviados)

    # El jefe la ve para validar, sin información clínica
    laura = entrar("laura@empresa.com")
    assert laura.get("/api/pendientes").json()["incapacidades"] >= 1
    pend = laura.get("/api/incapacidades", params={"por_aprobar": True, "estado": "solicitado"}).json()
    assert any(i["id"] == inc["id"] for i in pend)
    resumen = laura.get(f"/api/consultas?usuario_id={carlos['id']}").json()
    fila = next(c for c in resumen if c["id"] == consulta["id"])
    assert "sintomas" not in fila and fila["incapacidad"]["folio"] == "IMSS-123"
    cal = entrar("carlos@empresa.com").get(f"/api/calendario?anio={inicio.year}").json()
    assert str(inicio) in {i["fecha"] for i in cal["incapacidades"]}

    # Solo el jefe (o GH) valida; quien la registró o el empleado, no
    assert ana_c.post(f"/api/incapacidades/{inc['id']}/validar").status_code in (403, 404)
    assert entrar("carlos@empresa.com").post(f"/api/incapacidades/{inc['id']}/validar").status_code == 403
    r = laura.post(f"/api/incapacidades/{inc['id']}/validar")
    assert r.status_code == 200 and r.json()["estado"] == "validado" and r.json()["revisado_por_nombre"] == "Laura Martínez"
    assert any("admin@empresa.com" in dest and "validada" in asunto for dest, asunto in enviados)  # aviso a GH
    with SessionLocal() as db:
        assert db.query(NotificacionCorreo).filter(NotificacionCorreo.incapacidad_id == inc["id"],
                                                   NotificacionCorreo.evento == "incapacidad_validada").count() == 1
    assert laura.post(f"/api/incapacidades/{inc['id']}/validar").status_code == 400

    # Validada ya no se modifica ni se borra con la consulta
    cambio = {**datos, "incapacidad": {**datos["incapacidad"], "fecha_fin": str(inicio + timedelta(days=5))}}
    assert ana_c.put(f"/api/consultas/{consulta['id']}", json=cambio).status_code == 400
    assert ana_c.delete(f"/api/consultas/{consulta['id']}").status_code == 400
    assert ana_c.put(f"/api/consultas/{consulta['id']}", json={**datos, "indicaciones": "Hidratación"}).status_code == 200

    # Sin el permiso ya no registra consultas
    assert _guardar(adm, _usuario(adm, "ana@empresa.com"), puede_consultas=False).status_code == 200
    assert ana_c.post("/api/consultas", json=datos).status_code == 403
    with SessionLocal() as db:  # limpieza: la consulta de prueba
        db.delete(db.get(ConsultaMedica, consulta["id"]))
        db.commit()


def test_rechazo_y_validacion_por_gh(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto)))
    medico = entrar("medico@empresa.com")
    adm = entrar("admin@empresa.com", "Admin123")
    carlos = next(p for p in medico.get("/api/consultas/pacientes?q=Carlos").json() if p["nombre"] == "Carlos Pérez")
    datos = {"paciente_id": carlos["id"], "fecha": str(HOY), "hora_inicio": "11:00", "sintomas": "Esguince de tobillo",
             "resultado": "envia_casa", "incapacidad": {"fecha_inicio": str(HOY), "fecha_fin": str(HOY), "tipo": "riesgo_trabajo"}}
    c = medico.post("/api/consultas", json=datos).json()
    laura = entrar("laura@empresa.com")
    assert laura.post(f"/api/incapacidades/{c['incapacidad']['id']}/rechazar", json={"motivo": ""}).status_code == 422
    r = laura.post(f"/api/incapacidades/{c['incapacidad']['id']}/rechazar", json={"motivo": "Faltó el folio del IMSS"})
    assert r.status_code == 200 and r.json()["estado"] == "rechazado"
    assert any("rechazada" in asunto for _, asunto in enviados)
    assert any(i["id"] == c["incapacidad"]["id"] for i in adm.get("/api/incapacidades", params={"todos": True}).json())

    # La pendiente se puede quitar de la consulta; GH también puede validar
    otra = medico.post("/api/consultas", json={**datos, "hora_inicio": "12:00"}).json()
    sin = medico.put(f"/api/consultas/{otra['id']}", json={**datos, "hora_inicio": "12:00", "incapacidad": None})
    assert sin.status_code == 200 and sin.json()["incapacidad"] is None
    lau = next(p for p in medico.get("/api/consultas/pacientes?q=Laura").json() if p["nombre"] == "Laura Martínez")
    jefa = medico.post("/api/consultas", json={**datos, "paciente_id": lau["id"]}).json()
    r = adm.post(f"/api/incapacidades/{jefa['incapacidad']['id']}/validar")
    assert r.status_code == 200 and r.json()["estado"] == "validado"
    with SessionLocal() as db:
        for cid in (c["id"], otra["id"], jefa["id"]):
            db.delete(db.get(ConsultaMedica, cid))
        db.commit()


def test_jefe_ajusta_dias_al_validar(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto, t)))
    medico = entrar("medico@empresa.com")
    carlos = next(p for p in medico.get("/api/consultas/pacientes?q=Carlos").json() if p["nombre"] == "Carlos Pérez")
    inicio = date(HOY.year + 1, 2, 2)
    datos = {"paciente_id": carlos["id"], "fecha": str(HOY), "hora_inicio": "13:00", "sintomas": "Lumbalgia",
             "resultado": "envia_casa", "incapacidad": {"fecha_inicio": str(inicio), "fecha_fin": str(inicio + timedelta(days=4))}}
    c = medico.post("/api/consultas", json=datos).json()
    iid = c["incapacidad"]["id"]
    laura = entrar("laura@empresa.com")
    malo = {"fecha_inicio": str(inicio + timedelta(days=3)), "fecha_fin": str(inicio)}
    assert laura.post(f"/api/incapacidades/{iid}/validar", json=malo).status_code == 422
    r = laura.post(f"/api/incapacidades/{iid}/validar", json={"fecha_inicio": str(inicio), "fecha_fin": str(inicio + timedelta(days=1)),
                                                               "comentario": "Solo 2 días según el certificado"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["estado"] == "validado" and v["dias"] == 2 and v["dias_original"] == 5
    assert v["fecha_fin_original"] == str(inicio + timedelta(days=4)) and v["nota_revision"] == "Solo 2 días según el certificado"
    # El calendario personal muestra solo los días validados
    cal = entrar("carlos@empresa.com").get(f"/api/calendario?anio={inicio.year}").json()
    dias = sorted(x["fecha"] for x in cal["incapacidades"] if x["id"] == iid)
    assert dias == [str(inicio), str(inicio + timedelta(days=1))] and all(x["estado"] == "validado" for x in cal["incapacidades"] if x["id"] == iid)
    # A GH le llegan las fechas originales y el comentario
    assert any("validada" in a and "ajustadas por el jefe" in t and "Solo 2 días" in t for _, a, t in enviados)
    with SessionLocal() as db:
        db.delete(db.get(ConsultaMedica, c["id"]))
        db.commit()


def test_bitacora_de_consultas_y_rechazo_del_jefe(monkeypatch):
    monkeypatch.setattr(correo, "enviar", lambda *a: None)
    from app.security import ahora
    inicio_prueba = (ahora() - timedelta(seconds=2)).isoformat()
    medico = entrar("medico@empresa.com")
    carlos = next(p for p in medico.get("/api/consultas/pacientes?q=Carlos").json() if p["nombre"] == "Carlos Pérez")
    datos = {"paciente_id": carlos["id"], "fecha": str(HOY), "hora_inicio": "15:00", "sintomas": "Migraña severa",
             "resultado": "envia_casa", "incapacidad": {"fecha_inicio": str(HOY), "fecha_fin": str(HOY + timedelta(days=1))}}
    c = medico.post("/api/consultas", json=datos).json()
    iid = c["incapacidad"]["id"]
    # El jefe la rechaza (con motivo)
    laura = entrar("laura@empresa.com")
    r = laura.post(f"/api/incapacidades/{iid}/rechazar", json={"motivo": "No presentó el certificado"})
    assert r.status_code == 200 and r.json()["estado"] == "rechazado"

    bit = medico.get("/api/consultas/bitacora", params={"q": "carlos"}).json()
    mios = [b for b in bit if b["consulta_id"] == c["id"] and b["fecha"] >= inicio_prueba]
    eventos = {b["evento"]: b for b in mios}
    assert {"consulta_registrada", "incapacidad_generada", "incapacidad_rechazada"} <= set(eventos)
    assert eventos["consulta_registrada"]["actor_nombre"] == "Dra. Patricia Ruiz"
    assert eventos["incapacidad_rechazada"]["actor_nombre"] == "Laura Martínez"
    assert "No presentó el certificado" in eventos["incapacidad_rechazada"]["detalle"]
    assert all("Migraña" not in (b["detalle"] or "") for b in bit)            # sin datos clínicos
    assert medico.get("/api/consultas/bitacora", params={"tipo": "incapacidad"}).json()[0]["evento"].startswith("incapacidad")
    # Un empleado sin permiso de consultas no la ve
    assert entrar("carlos@empresa.com").get("/api/consultas/bitacora").status_code == 403
    with SessionLocal() as db:
        db.delete(db.get(ConsultaMedica, c["id"]))
        db.commit()
