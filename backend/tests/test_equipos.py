"""Salida de equipos de cómputo (F-630-03): empleado solicita, jefe autoriza, TI sella o rechaza y caseta registra."""
from datetime import date, timedelta

from app import correo
from app.database import SessionLocal
from app.models import SalidaEquipo, Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.seed import main as seed
from tests.test_api import FIRMA
from tests.test_caseta import _caseta
from tests.test_consultas import entrar

seed()
HOY = date.today()


def _ti():
    with SessionLocal() as db:
        if not db.query(Usuario).filter(Usuario.email == "ti@empresa.com").first():
            db.add(Usuario(numero_empleado="TI-1", nombre="Analista TI", email="ti@empresa.com", rol="oficina", puede_ti=True,
                           password_hash=hash_password("Cambiar123"), fecha_ingreso=date(2023, 1, 1),
                           sede_id=sede_principal(db).id))
            db.commit()
    return entrar("ti@empresa.com")


def _datos(**extra):
    return {"tipo_equipo": "laptop", "marca": "Dell", "modelo": "Latitude 5440", "serie": "8HX2KT3", "accesorios": "Cargador, mouse",
            "justificacion": "Trabajo en sitio con cliente", "fecha_inicio": str(HOY), "fecha_fin": str(HOY + timedelta(days=2)),
            "detalles": "Equipo asignado", **extra}


def _limpiar(*ids):
    with SessionLocal() as db:
        for i in ids:
            s = db.get(SalidaEquipo, i)
            if s:
                db.delete(s)
        db.commit()


def test_flujo_salida_de_equipo(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto)))
    carlos, laura, ti, cas = entrar("carlos@empresa.com"), entrar("laura@empresa.com"), _ti(), _caseta()
    assert "equipos:revisar" in ti.get("/api/auth/me").json()["permissions"]

    # Validaciones del formato y firma obligatoria para enviar
    assert carlos.post("/api/equipos", json=_datos(fecha_fin=str(HOY - timedelta(days=1)))).status_code == 422
    assert carlos.post("/api/equipos", json=_datos(enviar=True)).status_code == 422
    r = carlos.post("/api/equipos", json=_datos(enviar=True, firma=FIRMA))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["estado"] == "solicitado" and s["aprobador_nombre"] == "Laura Martínez" and s["situacion"] == "Esperando al jefe"
    assert any("laura@empresa.com" in d and "por autorizar" in a for d, a in enviados)

    # El jefe la ve en su bandeja y la autoriza; caseta ya la ve para hoy
    assert laura.get("/api/pendientes").json()["equipos"] >= 1
    assert any(x["id"] == s["id"] for x in laura.get("/api/equipos", params={"por_aprobar": True}).json())
    assert carlos.post(f"/api/equipos/{s['id']}/validar").status_code == 403
    v = laura.post(f"/api/equipos/{s['id']}/validar").json()
    assert v["estado"] == "validado" and v["puede_salir"] and v["situacion"] == "Autorizada por el jefe"
    assert any(x["id"] == s["id"] and x["puede_salir"] for x in cas.get("/api/equipos/hoy").json()["salidas"])

    # TI la ve pendiente de revisión y la sella
    assert ti.get("/api/pendientes").json()["ti_equipos"] >= 1
    lista = ti.get("/api/equipos", params={"todos": True, "estado": "revision_ti", "q": "8hx2"}).json()
    assert any(x["id"] == s["id"] for x in lista)
    a = ti.post(f"/api/equipos/{s['id']}/ti/autorizar", json={"nota": "Equipo inventariado", "firma": FIRMA}).json()
    assert a["ti_estado"] == "autorizado" and a["ti_por_nombre"] == "Analista TI" and a["tiene_firma_ti"]

    # Caseta registra la salida y el regreso; ya no se puede rechazar
    assert carlos.post(f"/api/equipos/{s['id']}/salida").status_code == 403
    sal = cas.post(f"/api/equipos/{s['id']}/salida").json()
    assert sal["situacion"] == "Fuera de planta" and sal["salida_por_nombre"] == "Guardia Caseta"
    assert ti.post(f"/api/equipos/{s['id']}/ti/rechazar", json={"motivo": "Tarde"}).status_code == 400
    assert cas.post(f"/api/equipos/{s['id']}/regreso").json()["situacion"] == "Regresó a planta"
    _limpiar(s["id"])


def test_ti_rechaza_y_avisa_al_empleado_y_al_jefe(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto)))
    carlos, laura, ti, cas = entrar("carlos@empresa.com"), entrar("laura@empresa.com"), _ti(), _caseta()
    s = carlos.post("/api/equipos", json=_datos(serie="SN-RECH-1", enviar=True, firma=FIRMA)).json()
    laura.post(f"/api/equipos/{s['id']}/validar")
    assert ti.post(f"/api/equipos/{s['id']}/ti/rechazar", json={"motivo": ""}).status_code == 422
    r = ti.post(f"/api/equipos/{s['id']}/ti/rechazar", json={"motivo": "El equipo no está en inventario"})
    assert r.status_code == 200, r.text
    x = r.json()
    assert x["estado"] == "rechazado" and x["ti_estado"] == "rechazado" and x["situacion"] == "Rechazada por TI" and not x["puede_salir"]
    aviso = next(d for d, asunto in enviados if "TI rechazó" in asunto)
    assert "laura@empresa.com" in aviso and any("carlos" in x for x in aviso)  # al jefe y al empleado
    # Caseta la ve como rechazada (no debe dejar salir el equipo) y no puede registrarla
    fila = next(f for f in cas.get("/api/equipos/hoy").json()["salidas"] if f["id"] == s["id"])
    assert fila["situacion"] == "Rechazada por TI" and not fila["puede_salir"]
    assert cas.post(f"/api/equipos/{s['id']}/salida").status_code == 400
    # El jefe también puede rechazar (motivo obligatorio) y el empleado cancelar
    s2 = carlos.post("/api/equipos", json=_datos(serie="SN-RECH-2", enviar=True, firma=FIRMA)).json()
    assert laura.post(f"/api/equipos/{s2['id']}/rechazar", json={"motivo": "No"}).status_code == 422
    assert laura.post(f"/api/equipos/{s2['id']}/rechazar", json={"motivo": "No es necesario"}).json()["situacion"] == "Rechazada por el jefe"
    s3 = carlos.post("/api/equipos", json=_datos(serie="SN-RECH-3", enviar=True, firma=FIRMA)).json()
    assert carlos.post(f"/api/equipos/{s3['id']}/cancelar").json()["estado"] == "cancelado"
    # Otro empleado no la ve
    assert entrar("ana@empresa.com").get(f"/api/equipos/{s['id']}").status_code == 404
    _limpiar(s["id"], s2["id"], s3["id"])


def test_ti_es_una_casilla_del_empleado():
    """TI no es un tipo de usuario: GH marca la casilla en la ficha y el empleado conserva sus vacaciones."""
    from tests.test_incapacidades import _guardar, _usuario
    adm = entrar("admin@empresa.com", "Admin123")
    ana = _usuario(adm, "ana@empresa.com")
    assert adm.put(f"/api/usuarios/{ana['id']}", json={**{k: ana.get(k) for k in ("numero_empleado", "nombre", "email", "fecha_ingreso")}, "rol": "ti"}).status_code == 422
    r = _guardar(adm, ana, puede_ti=True)
    assert r.status_code == 200 and r.json()["puede_ti"] and r.json()["rol"] == "oficina"
    a = entrar("ana@empresa.com")
    assert "equipos:revisar" in a.get("/api/auth/me").json()["permissions"]
    assert a.get("/api/equipos", params={"todos": True}).status_code == 200
    assert a.post("/api/vacaciones/calcular", json={"fecha_inicio": "2030-03-04", "fecha_fin": "2030-03-04"}).status_code == 200
    assert _guardar(adm, _usuario(adm, "ana@empresa.com"), puede_ti=False).json()["puede_ti"] is False
    assert "equipos:revisar" not in a.get("/api/auth/me").json()["permissions"]
