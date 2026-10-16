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
    {"name": "Modified", "displayName": "Modificado", "readOnly": True, "dateTime": {}},
]


@pytest.fixture
def graph(monkeypatch):
    for k, v in dict(microsoft_auth_enabled=True, microsoft_graph_enabled=True, microsoft_tenant_id="t",
                     microsoft_client_id="c", microsoft_client_secret="s", microsoft_authority_host="https://login.test",
                     microsoft_graph_url="https://graph.test/v1.0").items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(sharepoint, "SEGUNDO_PLANO", False)
    estado = {"items": {}, "llamadas": [], "negar": False}

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
                            "Estatus": "estado"}
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
