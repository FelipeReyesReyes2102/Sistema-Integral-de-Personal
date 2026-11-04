"""Autorización del jefe de una salida de equipo desde Teams: por lista de SharePoint y por flujo HTTP (Graph simulado)."""
from app import aprobacion_flujo as af
from app import correo, sharepoint
from tests.test_aprobacion_flujo import FLUJO, LISTA, entorno  # noqa: F401 (fixture)
from tests.test_equipos import _datos, _limpiar
from tests.test_consultas import entrar
from tests.test_sharepoint import URL, graph, super_login  # noqa: F401 (fixture)
from tests.test_api import FIRMA

TEAMS = {"aprobacion_teams": True, "col_decision": "Decision", "col_comentario": "ComentarioTeams",
         "col_respondio": "Respondio", "cuenta_flujo": "Flujos@o-tek.com"}


def _salida(carlos):
    r = carlos.post("/api/equipos", json=_datos(enviar=True, firma=FIRMA))
    assert r.status_code == 201, r.text
    sharepoint.procesar_pendientes()  # en pruebas el envío en segundo plano está apagado
    return r.json()


def test_salida_de_equipo_se_autoriza_en_teams_por_lista(graph, monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto)))
    adm, carlos, laura = super_login(), entrar("carlos@empresa.com"), entrar("laura@empresa.com")
    cfg = adm.put("/api/sharepoint/equipos/conectar", json={"url": URL}).json()
    assert cfg["mapeo"]["Title"] == "folio" and cfg["mapeo"]["CorreoJefe"] == "correo_jefe"
    assert any(c["clave"] == "serie" for c in cfg["campos"])
    r = adm.put("/api/sharepoint/equipos", json={"activo": True, "mapeo": cfg["mapeo"], "valores": cfg["valores"], **TEAMS})
    assert r.status_code == 200, r.text
    jefa = laura.get("/api/auth/me").json()
    ids = []
    try:
        # 1) La solicitud llega a la lista con el correo de la jefa; el flujo escribe Approve
        s = _salida(carlos)
        ids.append(s["id"])
        item = next(k for k, v in graph["items"].items() if v["Title"] == f"EQ-{s['id']}")
        assert graph["items"][item]["CorreoJefe"] == jefa["email"]
        assert sharepoint.revisar_decisiones() == 0
        graph["items"][item].update({"Decision": "Approve", "Respondio": jefa["email"]})
        assert sharepoint.revisar_decisiones() == 1
        s = adm.get(f"/api/equipos/{s['id']}").json()
        assert s["estado"] == "validado" and s["situacion"] == "Autorizada por el jefe"
        assert any("autoriz" in a.lower() for _, a in enviados)  # mismo aviso que al autorizar en SIP-O
        b = adm.get("/api/bitacora", params={"seccion": "vacaciones", "entidad": "Salida de equipo"}).json()["items"]
        assert any(x["ip"] == "Teams (Power Automate)" for x in b)

        # 2) Rechazo sin comentario: queda rechazada con un motivo que lo explica
        s2 = _salida(carlos)
        ids.append(s2["id"])
        item2 = next(k for k, v in graph["items"].items() if v["Title"] == f"EQ-{s2['id']}")
        graph["items"][item2].update({"Decision": "Reject", "Respondio": jefa["email"]})
        assert sharepoint.revisar_decisiones() == 1
        s2 = adm.get(f"/api/equipos/{s2['id']}").json()
        assert s2["estado"] == "rechazado" and s2["motivo_rechazo"] == "Rechazada en Teams sin comentario."

        # 3) Si responde quien no puede autorizar (el propio solicitante), se ignora con una nota
        s3 = _salida(carlos)
        ids.append(s3["id"])
        item3 = next(k for k, v in graph["items"].items() if v["Title"] == f"EQ-{s3['id']}")
        graph["items"][item3].update({"Decision": "Approve", "Respondio": "carlos@empresa.com"})
        assert sharepoint.revisar_decisiones() == 0
        assert adm.get(f"/api/equipos/{s3['id']}").json()["estado"] == "solicitado"
        assert "no puede aprobar" in adm.get("/api/sharepoint").json()["listas"]["equipos"]["notas_teams"][0]["nota"]
    finally:
        adm.delete("/api/sharepoint/equipos")
        _limpiar(*ids)


def test_salida_de_equipo_se_autoriza_en_teams_por_flujo_http(entorno, monkeypatch):  # noqa: F811
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: None)
    adm, carlos, laura = super_login(), entrar("carlos@empresa.com"), entrar("laura@empresa.com")
    r = adm.put("/api/aprobacion-flujo", json={"activo": True, "tipos": ["equipos"], "flujo_url": FLUJO,
                                               "lista_url": LISTA, "cuenta_flujo": "Flujos@o-tek.com"})
    assert r.status_code == 200, r.text
    assert r.json()["tipos"] == ["equipos"]
    jefa = laura.get("/api/auth/me").json()
    ids = []
    try:
        s = _salida(carlos)
        ids.append(s["id"])
        af.enviar_pendientes()
        env = entorno["enviados"][-1]
        assert env["folio"] == f"EQ-{s['id']}" and env["tipo"] == "equipos" and env["correoJefe"] == jefa["email"]
        assert env["titulo"].startswith("Salida de equipo de") and "Serie / Service Tag" in env["detalles"]

        entorno["decisiones"].append({"Token": env["token"], "Decision": "Approve", "Respondio": jefa["email"]})
        assert af.revisar_decisiones() == 1
        assert adm.get(f"/api/equipos/{s['id']}").json()["estado"] == "validado"

        # Rechazo con comentario: el comentario queda como motivo
        antes = len(entorno["enviados"])
        s2 = _salida(carlos)
        ids.append(s2["id"])
        af.enviar_pendientes()
        assert len(entorno["enviados"]) == antes + 1
        entorno["decisiones"].append({"Token": entorno["enviados"][-1]["token"], "Decision": "Reject",
                                      "Respondio": jefa["email"], "Comentario": "No es necesario llevarla"})
        assert af.revisar_decisiones() == 1
        s2 = adm.get(f"/api/equipos/{s2['id']}").json()
        assert s2["estado"] == "rechazado" and s2["motivo_rechazo"] == "No es necesario llevarla"
    finally:
        adm.put("/api/aprobacion-flujo", json={"activo": False})
        _limpiar(*ids)
