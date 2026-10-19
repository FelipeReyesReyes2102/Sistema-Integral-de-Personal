"""Envío de solicitudes a listas de SharePoint (Graph simulado con httpx.MockTransport)."""
from datetime import date, timedelta

import httpx
import pytest

from app import microsoft, sharepoint
from app.config import settings
from app.seed import main as seed
from tests.test_api import FIRMA, login

seed()
URL = "https://otek.sharepoint.com/sites/GH/Lists/Vacaciones%20SIP/AllItems.aspx"
COLUMNAS = [
    {"name": "Title", "displayName": "Título", "required": True, "text": {}},
    {"name": "Empleado", "displayName": "Empleado", "text": {}},
    {"name": "FechaInicio", "displayName": "Fecha inicio", "dateTime": {"format": "dateOnly"}},
    {"name": "Dias", "displayName": "Días", "number": {}},
    {"name": "Estatus", "displayName": "Estatus", "choice": {"choices": ["Pendiente", "Aprobado", "Rechazado", "Cancelado"]}},
    {"name": "Jefe", "displayName": "Jefe inmediato", "personOrGroup": {}},
    {"name": "CorreoJefe", "displayName": "Correo del jefe", "text": {}},
    {"name": "Decision", "displayName": "Decisión Teams", "text": {}},
    {"name": "ComentarioTeams", "displayName": "Comentario Teams", "text": {}},
    {"name": "Respondio", "displayName": "Respondió", "text": {}},
    {"name": "Modified", "displayName": "Modificado", "readOnly": True, "dateTime": {}},
]


@pytest.fixture
def graph(monkeypatch):
    for k, v in dict(microsoft_auth_enabled=True, microsoft_graph_enabled=True, microsoft_tenant_id="t",
                     microsoft_client_id="c", microsoft_client_secret="s", microsoft_authority_host="https://login.test",
                     microsoft_graph_url="https://graph.test/v1.0").items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(sharepoint, "SEGUNDO_PLANO", False)
    estado = {"items": {}, "llamadas": [], "negar": False, "modificado": {"user": {"email": "flujos@o-tek.com"}}}

    def manejador(req: httpx.Request):
        p = req.url.path
        if p.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "a.e30.b", "expires_in": 3600})
        if estado["negar"]:
            return httpx.Response(403, json={"error": {"code": "accessDenied", "message": "Access denied"}})
        if p == "/v1.0/sites/otek.sharepoint.com:/sites/GH":
            return httpx.Response(200, json={"id": "sitio1", "displayName": "Gestión Humana"})
        if p == "/v1.0/sites/sitio1/lists":
            return httpx.Response(200, json={"value": [
                {"id": "otra", "displayName": "Permisos", "webUrl": "https://otek.sharepoint.com/sites/GH/Lists/Permisos"},
                {"id": "lista1", "displayName": "Vacaciones SIP", "webUrl": "https://otek.sharepoint.com/sites/GH/Lists/Vacaciones%20SIP"}]})
        if p == "/v1.0/sites/sitio1/lists/lista1/columns":
            return httpx.Response(200, json={"value": COLUMNAS})
        if p == "/v1.0/sites/sitio1/lists/lista1/items" and req.method == "POST":
            import json
            n = str(len(estado["items"]) + 1)
            estado["items"][n] = json.loads(req.content)["fields"]
            estado["llamadas"].append(("POST", n))
            return httpx.Response(201, json={"id": n})
        if p.startswith("/v1.0/sites/sitio1/lists/lista1/items/") and req.method == "GET":
            n = p.split("/")[-1]
            if n not in estado["items"]:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": n, "lastModifiedBy": estado["modificado"], "fields": estado["items"][n]})
        if p.startswith("/v1.0/sites/sitio1/lists/lista1/items/") and req.method == "PATCH":
            import json
            n = p.split("/")[-2]
            if n not in estado["items"]:
                return httpx.Response(404)
            estado["items"][n].update(json.loads(req.content))
            estado["llamadas"].append(("PATCH", n))
            return httpx.Response(200, json={})
        return httpx.Response(404)
    microsoft.transporte = httpx.MockTransport(manejador)
    microsoft._token_app.update(valor=None, expira=0)
    yield estado
    microsoft.transporte = None
    microsoft._token_app.update(valor=None, expira=0)


def test_url_invalida():
    with pytest.raises(sharepoint.ErrorSharePoint):
        sharepoint.analizar_url("https://otek.sharepoint.com/sites/GH/Documentos")
    assert sharepoint.analizar_url(URL) == ("otek.sharepoint.com", "/sites/GH", "Vacaciones SIP")


def test_envio_y_actualizacion(graph):
    adm, ana = login("admin@empresa.com", "Admin123"), login("ana@empresa.com", "Cambiar123")
    r = adm.put("/api/sharepoint/vacaciones/conectar", json={"url": URL})
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["lista_nombre"] == "Vacaciones SIP" and "Modified" not in {c["nombre"] for c in cfg["columnas"]}
    # Mapeo sugerido por nombre y equivalencias de opciones (Validado -> Aprobado)
    assert cfg["mapeo"] == {"Title": "folio", "Empleado": "empleado", "FechaInicio": "fecha_inicio", "Dias": "dias",
                            "Estatus": "estado", "CorreoJefe": "correo_jefe"}
    assert cfg["valores"]["Estatus"]["validado"] == "Aprobado" and cfg["valores"]["Estatus"]["solicitado"] == "Pendiente"

    # Columna de persona no se puede llenar; Título es obligatoria
    assert adm.put("/api/sharepoint/vacaciones", json={"activo": True, "mapeo": {**cfg["mapeo"], "Jefe": "jefe"}}).status_code == 422
    sin_titulo = {k: v for k, v in cfg["mapeo"].items() if k != "Title"}
    assert "Título" in adm.put("/api/sharepoint/vacaciones", json={"activo": True, "mapeo": sin_titulo}).json()["detail"]
    r = adm.put("/api/sharepoint/vacaciones", json={"activo": True, "mapeo": cfg["mapeo"], "valores": cfg["valores"]})
    assert r.status_code == 200 and r.json()["activo"]

    # Ana pide vacaciones: el borrador no se envía; al enviarla, se crea el elemento
    p = ana.get("/api/periodos").json()[0]
    adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 80, "nota_ajuste": "prueba sharepoint"})
    d = date.today() + timedelta(weeks=40)
    lunes = d - timedelta(days=d.weekday())
    sol = ana.post("/api/vacaciones", json={"periodo_id": p["id"], "fecha_inicio": str(lunes),
                                            "fecha_fin": str(lunes + timedelta(days=7)), "firma": FIRMA}).json()
    sharepoint.procesar_pendientes()
    assert graph["items"] == {}
    ana.post(f"/api/vacaciones/{sol['id']}/enviar")
    assert sharepoint.procesar_pendientes() == 1
    item = graph["items"]["1"]
    assert item["Title"] == f"VAC-{sol['id']}" and item["Empleado"].startswith("Ana") and item["Dias"] == 6.0
    from app.database import SessionLocal
    from app.models import SolicitudVacaciones
    with SessionLocal() as db:
        datos = sharepoint.datos_registro("vacaciones", db.get(SolicitudVacaciones, sol["id"]))
    assert datos["fecha_ingreso"] and datos["dias_periodo"] > 0 and datos["saldo_periodo"] is not None
    assert item["Estatus"] == "Pendiente" and item["FechaInicio"] == f"{lunes}T06:00:00Z"  # medianoche en México

    # Validar actualiza el mismo elemento
    adm.post(f"/api/vacaciones/{sol['id']}/validar")
    sharepoint.procesar_pendientes()
    assert graph["llamadas"][-1] == ("PATCH", "1") and graph["items"]["1"]["Estatus"] == "Aprobado"
    assert len(graph["items"]) == 1

    # Si Microsoft niega el acceso, queda en error con un mensaje claro y se puede reintentar
    graph["negar"] = True
    adm.post(f"/api/vacaciones/{sol['id']}/cancelar")
    ana.post(f"/api/vacaciones/{sol['id']}/cancelar")
    sharepoint.procesar_pendientes()
    est = adm.get("/api/sharepoint").json()["listas"]["vacaciones"]
    assert est["cuentas"]["error"] == 1 and "Sites.ReadWrite.All" in est["errores"][0]["error"]
    graph["negar"] = False
    adm.post("/api/sharepoint/vacaciones/reintentar")
    sharepoint.procesar_pendientes()
    assert graph["items"]["1"]["Estatus"] == "Cancelado"
    assert adm.get("/api/sharepoint").json()["listas"]["vacaciones"]["cuentas"] == {"enviado": 1, "pendiente": 0, "error": 0}

    # Historial: "enviar existentes" no duplica lo ya enviado
    r = adm.post("/api/sharepoint/vacaciones/existentes", json={"desde": "2000-01-01"})
    assert r.status_code == 200
    sharepoint.procesar_pendientes()
    assert sum(1 for v in graph["items"].values() if v["Title"] == f"VAC-{sol['id']}") == 1

    adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 0, "nota_ajuste": None})
    assert adm.delete("/api/sharepoint/vacaciones").json()["conectada"] is False


def _solicitud(adm, ana, semanas):
    p = ana.get("/api/periodos").json()[0]
    adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 80, "nota_ajuste": "prueba teams"})
    d = date.today() + timedelta(weeks=semanas)
    lunes = d - timedelta(days=d.weekday())
    r = ana.post("/api/vacaciones", json={"periodo_id": p["id"], "fecha_inicio": str(lunes),
                                          "fecha_fin": str(lunes + timedelta(days=7)), "firma": FIRMA, "enviar": True})
    assert r.status_code == 201, r.text
    sharepoint.procesar_pendientes()
    return r.json(), p


def test_aprobacion_en_teams(graph):
    adm, ana = login("admin@empresa.com", "Admin123"), login("ana@empresa.com", "Cambiar123")
    cfg = adm.put("/api/sharepoint/vacaciones/conectar", json={"url": URL}).json()
    teams = {"aprobacion_teams": True, "col_decision": "Decision", "col_comentario": "ComentarioTeams",
             "col_respondio": "Respondio", "cuenta_flujo": "Flujos@o-tek.com"}
    base = {"activo": True, "mapeo": cfg["mapeo"], "valores": cfg["valores"]}
    # Validaciones: la columna de decisión no puede llevar datos de SIP-O; se necesita el correo del jefe
    malo = adm.put("/api/sharepoint/vacaciones", json={**base, **teams, "mapeo": {**cfg["mapeo"], "Decision": "comentario"}})
    assert malo.status_code == 422 and "flujo" in malo.json()["detail"]
    sin_correo = {k: v for k, v in cfg["mapeo"].items() if v != "correo_jefe"}
    assert "Correo del jefe" in adm.put("/api/sharepoint/vacaciones", json={**base, **teams, "mapeo": sin_correo}).json()["detail"]
    r = adm.put("/api/sharepoint/vacaciones", json={**base, **teams})
    assert r.status_code == 200, r.text
    assert r.json()["teams"]["activo"] and r.json()["teams"]["val_aprobado"] == "Approve"

    # 1) Se aprueba en Teams: el flujo escribe Approve y el correo del jefe
    sol, p = _solicitud(adm, ana, 14)
    item_id = next(k for k, v in graph["items"].items() if v["Title"] == f"VAC-{sol['id']}")
    jefe = adm.get(f"/api/usuarios/{sol['aprobador_id']}").json()
    assert graph["items"][item_id]["CorreoJefe"] == jefe["email"]
    assert sharepoint.revisar_decisiones() == 0  # aún sin decisión
    graph["items"][item_id].update({"Decision": "Approve", "Respondio": jefe["email"], "ComentarioTeams": "Disfruta"})
    assert sharepoint.revisar_decisiones() == 1
    s = adm.get(f"/api/vacaciones/{sol['id']}").json()
    assert s["estado"] == "validado"
    assert graph["items"][item_id]["Estatus"] == "Aprobado"  # SIP-O actualizó la lista
    e = adm.get("/api/bitacora", params={"seccion": "vacaciones", "entidad": "Solicitud de vacaciones"}).json()["items"][0]
    assert e["accion"] == "estado" and e["actor_nombre"] == jefe["nombre"] and e["ip"] == "Teams (Power Automate)"
    adm.post(f"/api/vacaciones/{sol['id']}/cancelar")
    sharepoint.procesar_pendientes()

    # 2) Rechazo en Teams con comentario
    sol, _ = _solicitud(adm, ana, 20)
    item_id = next(k for k, v in graph["items"].items() if v["Title"] == f"VAC-{sol['id']}")
    graph["items"][item_id].update({"Decision": "Reject", "Respondio": jefe["email"], "ComentarioTeams": "Cierre de mes"})
    sharepoint.revisar_decisiones()
    s = adm.get(f"/api/vacaciones/{sol['id']}").json()
    assert s["estado"] == "rechazado" and s["motivo_rechazo"] == "Cierre de mes"

    # 3) Seguridad: alguien edita la columna a mano (no es la cuenta del flujo) o responde otra persona
    sol, _ = _solicitud(adm, ana, 26)
    item_id = next(k for k, v in graph["items"].items() if v["Title"] == f"VAC-{sol['id']}")
    graph["items"][item_id].update({"Decision": "Approve", "Respondio": jefe["email"]})
    graph["modificado"] = {"user": {"email": "ana@empresa.com", "displayName": "Ana"}}
    assert sharepoint.revisar_decisiones() == 0
    assert adm.get(f"/api/vacaciones/{sol['id']}").json()["estado"] == "solicitado"
    notas = adm.get("/api/sharepoint").json()["listas"]["vacaciones"]["notas_teams"]
    assert "no la cuenta del flujo" in notas[0]["nota"]
    graph["modificado"] = {"user": {"email": "flujos@o-tek.com"}}
    graph["items"][item_id]["Respondio"] = "ana@empresa.com"  # la propia empleada no puede aprobarse
    assert sharepoint.revisar_decisiones() == 0
    assert "no puede aprobar" in adm.get("/api/sharepoint").json()["listas"]["vacaciones"]["notas_teams"][0]["nota"]
    # Aprobada desde SIP-O mientras tanto: la decisión de Teams ya no se aplica
    adm.post(f"/api/vacaciones/{sol['id']}/cancelar")
    graph["items"][item_id]["Respondio"] = jefe["email"]
    assert sharepoint.revisar_decisiones() == 0

    adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 0, "nota_ajuste": None})
    adm.delete("/api/sharepoint/vacaciones")


def test_permiso_fecha_hora_en_zona_de_la_sede():
    from datetime import time as t_
    from types import SimpleNamespace as N
    sede = N(nombre="O-tek México", zona_horaria="America/Mexico_City")
    u = N(nombre="Ana", numero_empleado="1001", email="ana@empresa.com", email_personal=None, puesto=None,
          departamento="IT", sede=sede)
    p = N(id=7, usuario=u, departamento=None, aprobador=None, estado="solicitado", motivo_rechazo=None, creado=None,
          revisado_por=None, fecha_revision=None, tipo="llegada_tarde", fecha=date(2026, 10, 20), fecha_fin=None,
          hora_inicio=t_(8, 30), hora_fin=t_(10, 0), horas=1.5, motivo="Cita", tipo_nomina="con_goce", observaciones=None)
    d = sharepoint.datos_registro("permisos", p)
    col = {"nombre": "field_9", "tipo": "dateTime", "opciones": []}
    assert sharepoint._convertir(d["fecha_hora_inicio"], col, "fecha_hora_inicio", "permisos", {}, None) == "2026-10-20T14:30:00Z"
    assert sharepoint._convertir(d["fecha_hora_fin"], col, "fecha_hora_fin", "permisos", {}, None) == "2026-10-20T16:00:00Z"
    tipo = {"nombre": "field_8", "tipo": "choice", "opciones": ["Sale Temprano", "Llega Tarde", "Sale y Regresa", "Home office"]}
    assert sharepoint._convertir("llegada_tarde", tipo, "tipo", "permisos", {"field_8": {"llegada_tarde": "Llega Tarde"}}, None) == "Llega Tarde"
