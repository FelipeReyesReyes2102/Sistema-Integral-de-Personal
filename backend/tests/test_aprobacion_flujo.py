"""Aprobación en Teams por flujo HTTP de Power Automate (flujo y Graph simulados)."""
import json
from datetime import date, timedelta

import httpx
import pytest

from app import aprobacion_flujo as af
from app import microsoft, sharepoint
from app.config import settings
from app.seed import main as seed
from tests.test_api import FIRMA, login
from tests.test_sharepoint import super_login

seed()
FLUJO = "https://prod-12.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=1&sig=SECRETO"
LISTA = "https://otek.sharepoint.com/sites/GH/Lists/Decisiones%20SIP-O/AllItems.aspx"


@pytest.fixture
def entorno(monkeypatch):
    for k, v in dict(microsoft_auth_enabled=True, microsoft_graph_enabled=True, microsoft_tenant_id="t",
                     microsoft_client_id="c", microsoft_client_secret="s", microsoft_authority_host="https://login.test",
                     microsoft_graph_url="https://graph.test/v1.0").items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(af, "SEGUNDO_PLANO", False)
    monkeypatch.setattr(sharepoint, "SEGUNDO_PLANO", False)
    e = {"enviados": [], "decisiones": [], "creador": "flujos@o-tek.com", "flujo_status": 202}

    def manejador(req: httpx.Request):
        p = req.url.path
        if p.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "a.e30.b", "expires_in": 3600})
        if req.url.host.endswith("logic.azure.com"):
            e["enviados"].append(json.loads(req.content))
            return httpx.Response(e["flujo_status"])
        if p == "/v1.0/sites/otek.sharepoint.com:/sites/GH":
            return httpx.Response(200, json={"id": "s1", "displayName": "GH"})
        if p == "/v1.0/sites/s1/lists":
            return httpx.Response(200, json={"value": [{"id": "d1", "displayName": "Decisiones SIP-O",
                                                        "webUrl": "https://otek.sharepoint.com/sites/GH/Lists/Decisiones%20SIP-O"}]})
        if p == "/v1.0/sites/s1/lists/d1/columns":
            return httpx.Response(200, json={"value": [{"name": n, "displayName": n, "text": {}} for n in
                                                       ("Title", "Token", "Decision", "Comentario", "Respondio", "Tipo")]})
        if p == "/v1.0/sites/s1/lists/d1/items":
            filtro = req.url.params.get("$filter", "")
            tok = filtro.split("'")[1] if "'" in filtro else None
            return httpx.Response(200, json={"value": [
                {"id": str(i), "createdBy": {"user": {"email": d.get("_creador", e["creador"])}}, "fields": d}
                for i, d in enumerate(e["decisiones"]) if d.get("Token") == tok]})
        return httpx.Response(404)
    microsoft.transporte = httpx.MockTransport(manejador)
    microsoft._token_app.update(valor=None, expira=0)
    yield e
    microsoft.transporte = None
    microsoft._token_app.update(valor=None, expira=0)


def _solicitar(adm, ana, semanas):
    p = ana.get("/api/periodos").json()[0]
    adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 80, "nota_ajuste": "prueba flujo"})
    d = date.today() + timedelta(weeks=semanas)
    lunes = d - timedelta(days=d.weekday())
    r = ana.post("/api/vacaciones", json={"periodo_id": p["id"], "fecha_inicio": str(lunes),
                                          "fecha_fin": str(lunes + timedelta(days=7)), "firma": FIRMA, "enviar": True})
    assert r.status_code == 201, r.text
    return r.json(), p


def test_flujo_http_completo(entorno):
    adm, ana = super_login(), login("ana@empresa.com", "Cambiar123")
    # Validaciones de configuración
    assert adm.put("/api/aprobacion-flujo", json={"activo": True}).status_code == 422
    assert adm.put("/api/aprobacion-flujo", json={"activo": False, "flujo_url": "https://evil.example.com/x"}).status_code == 422
    r = adm.put("/api/aprobacion-flujo", json={"activo": True, "tipos": ["vacaciones", "permisos"], "flujo_url": FLUJO,
                                               "lista_url": LISTA, "cuenta_flujo": "Flujos@o-tek.com"})
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["activo"] and est["configurado"] and est["lista_nombre"] == "Decisiones SIP-O"
    assert "SECRETO" not in json.dumps(est)  # la URL nunca regresa al navegador
    e = adm.get("/api/bitacora", params={"seccion": "configuracion", "entidad": "Aprobación en Teams"}).json()["items"][0]
    assert {"campo": "URL del flujo", "antes": None, "despues": "(valor oculto)"} in e["cambios"]

    # 1) Al enviarse la solicitud, SIP-O llama al flujo con los datos y un token
    sol, p = _solicitar(adm, ana, 16)
    af.enviar_pendientes()
    env = entorno["enviados"][-1]
    jefe = adm.get(f"/api/usuarios/{sol['aprobador_id']}").json()
    assert env["folio"] == f"VAC-{sol['id']}" and env["correoJefe"] == jefe["email"] and len(env["token"]) > 20
    assert "Días hábiles" in env["detalles"] and env["titulo"].startswith("Vacaciones de")
    assert af.revisar_decisiones() == 0  # sin respuesta aún

    # 2) Decisión con token equivocado o creada por otra cuenta: se ignora
    entorno["decisiones"].append({"Title": env["folio"], "Token": "otro", "Decision": "Approve", "Respondio": jefe["email"]})
    entorno["decisiones"].append({"Title": env["folio"], "Token": env["token"], "Decision": "Approve",
                                  "Respondio": jefe["email"], "_creador": "ana@empresa.com"})
    assert af.revisar_decisiones() == 0
    assert adm.get(f"/api/vacaciones/{sol['id']}").json()["estado"] == "solicitado"
    assert "no la cuenta del flujo" in adm.get("/api/aprobacion-flujo").json()["avisos"][0]["texto"]

    # 3) Decisión válida del flujo: se aplica
    entorno["decisiones"].append({"Title": env["folio"], "Token": env["token"], "Decision": "Approve",
                                  "Respondio": jefe["email"], "Comentario": "Ok"})
    assert af.revisar_decisiones() == 1
    s = adm.get(f"/api/vacaciones/{sol['id']}").json()
    assert s["estado"] == "validado"
    b = adm.get("/api/bitacora", params={"seccion": "vacaciones", "entidad": "Solicitud de vacaciones"}).json()["items"][0]
    assert b["actor_nombre"] == jefe["nombre"] and b["ip"] == "Teams (Power Automate)"
    adm.post(f"/api/vacaciones/{sol['id']}/cancelar")

    # 4) Rechazo con comentario; y si se resuelve primero en SIP-O, la respuesta posterior se ignora
    sol2, _ = _solicitar(adm, ana, 22)
    af.enviar_pendientes()
    tok2 = entorno["enviados"][-1]["token"]
    entorno["decisiones"].append({"Token": tok2, "Decision": "Reject", "Respondio": jefe["email"], "Comentario": "Inventario"})
    af.revisar_decisiones()
    s2 = adm.get(f"/api/vacaciones/{sol2['id']}").json()
    assert s2["estado"] == "rechazado" and s2["motivo_rechazo"] == "Inventario"

    sol3, _ = _solicitar(adm, ana, 28)
    af.enviar_pendientes()
    tok3 = entorno["enviados"][-1]["token"]
    adm.post(f"/api/vacaciones/{sol3['id']}/cancelar")
    entorno["decisiones"].append({"Token": tok3, "Decision": "Approve", "Respondio": jefe["email"]})
    assert af.revisar_decisiones() == 0
    assert adm.get(f"/api/vacaciones/{sol3['id']}").json()["estado"] == "cancelado"

    # 5) Si el flujo falla, queda en error y se puede reintentar
    entorno["flujo_status"] = 500
    sol4, _ = _solicitar(adm, ana, 34)
    af.enviar_pendientes()
    assert adm.get("/api/aprobacion-flujo").json()["cuentas"]["error"] == 1
    entorno["flujo_status"] = 202
    assert adm.post("/api/aprobacion-flujo/reintentar").json()["cuentas"]["error"] == 0
    adm.post(f"/api/vacaciones/{sol4['id']}/cancelar")

    adm.put(f"/api/periodos/{p['id']}/ajuste", json={"ajuste_horas": 0, "nota_ajuste": None})
    adm.put("/api/aprobacion-flujo", json={"activo": False})
