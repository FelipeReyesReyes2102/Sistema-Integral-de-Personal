"""Bitácora: cambios de configuración y de vacaciones, agrupados, legibles y sin secretos."""
from fastapi.testclient import TestClient

from app.main import app
from app.seed import main as seed

seed()


def _admin():
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": "admin@empresa.com", "password": "Admin123"}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def _ultima(c, seccion, **f):
    r = c.get("/api/bitacora", params={"seccion": seccion, "limite": 5, **f})
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_turno_crear_editar_eliminar():
    c = _admin()
    datos = {"nombre": "Turno bitácora", "hora_entrada": "08:30", "hora_salida": "17:00", "horas_jornada": 8,
             "dias": [{"dia": 4, "hora_entrada": "08:30", "hora_salida": "15:00"}]}
    t = c.post("/api/turnos", json=datos).json()
    e = _ultima(c, "configuracion", entidad="Turno")
    assert e["accion"] == "crear" and e["descripcion"] == "Turno bitácora" and e["actor_nombre"]
    campos = {x["campo"]: x for x in e["cambios"]}
    assert campos["Entrada"]["despues"] == "08:30" and campos["Horario Viernes"]["despues"] == "08:30–15:00"

    # Editar: mismo horario por día (no debe aparecer) y nuevo Short Friday; cambia la salida general
    c.put(f"/api/turnos/{t['id']}", json={**datos, "hora_salida": "17:30", "especiales": [
        {"nombre": "Short Friday", "fecha_inicio": "2026-10-16", "dias": [4], "cada_semanas": 2,
         "hora_entrada": "08:30", "hora_salida": "13:00"}]})
    e = _ultima(c, "configuracion", entidad="Turno")
    campos = {x["campo"]: x for x in e["cambios"]}
    assert e["accion"] == "editar" and "Horario Viernes" not in campos
    assert campos["Salida"] == {"campo": "Salida", "antes": "17:00", "despues": "17:30"}
    assert campos["Horario especial «Short Friday»"]["antes"] is None
    assert "cada 2 semanas" in campos["Horario especial «Short Friday»"]["despues"]

    # Guardar sin cambios no registra nada
    total = len(c.get("/api/bitacora", params={"seccion": "configuracion", "limite": 200}).json()["items"])
    c.put(f"/api/turnos/{t['id']}", json={**datos, "hora_salida": "17:30", "especiales": [
        {"nombre": "Short Friday", "fecha_inicio": "2026-10-16", "dias": [4], "cada_semanas": 2,
         "hora_entrada": "08:30", "hora_salida": "13:00"}]})
    assert len(c.get("/api/bitacora", params={"seccion": "configuracion", "limite": 200}).json()["items"]) == total

    assert c.delete(f"/api/turnos/{t['id']}").status_code == 204
    e = _ultima(c, "configuracion", entidad="Turno")
    assert e["accion"] == "eliminar" and e["descripcion"] == "Turno bitácora"


def test_secretos_ocultos_y_busqueda():
    c = _admin()
    r = c.get("/api/bitacora", params={"seccion": "configuracion", "q": "zzz-no-existe"})
    assert r.json()["items"] == []
    for it in c.get("/api/bitacora", params={"seccion": "configuracion", "limite": 200}).json()["items"]:
        for x in it["cambios"]:
            if "password" in x["campo"].lower() or "secret" in x["campo"].lower():
                assert x["despues"] in (None, "(valor oculto)")
    assert c.get("/api/bitacora", params={"seccion": "otra"}).status_code == 422


def test_solo_administradores():
    c = TestClient(app)
    assert c.get("/api/bitacora", params={"seccion": "vacaciones"}).status_code == 401


def test_vacaciones_y_saldo():
    from datetime import date, timedelta

    from tests.test_api import FIRMA, login
    adm, ana = _admin(), login("ana@empresa.com", "Cambiar123")
    p = ana.get("/api/periodos").json()[0]
    assert adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 80, "nota_ajuste": "Prueba bitácora"}).status_code == 200
    e = _ultima(adm, "vacaciones", entidad="Saldo de vacaciones")
    assert "Ana" in e["descripcion"] and "80 h (Prueba bitácora)" in e["cambios"][0]["despues"]

    d = date.today() + timedelta(weeks=30)
    lunes = d - timedelta(days=d.weekday())
    r = ana.post("/api/vacaciones", json={"periodo_id": p["id"], "fecha_inicio": str(lunes),
                                          "fecha_fin": str(lunes + timedelta(days=7)), "firma": FIRMA})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    e = _ultima(adm, "vacaciones", entidad="Solicitud de vacaciones")
    assert e["accion"] == "crear" and e["actor_nombre"].startswith("Ana")
    campos = {x["campo"]: x["despues"] for x in e["cambios"]}
    assert campos["Estado"] == "Borrador" and campos["Firma"] == "(firma)"
    assert ana.post(f"/api/vacaciones/{sid}/enviar").status_code == 200
    e = _ultima(adm, "vacaciones", entidad="Solicitud de vacaciones")
    assert e["accion"] == "estado" and {"campo": "Estado", "antes": "Borrador", "despues": "Solicitado"} in e["cambios"]
    assert ana.post(f"/api/vacaciones/{sid}/cancelar").status_code == 200
    adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 0, "nota_ajuste": None})
