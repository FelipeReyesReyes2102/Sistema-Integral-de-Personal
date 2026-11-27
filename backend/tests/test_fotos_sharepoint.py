"""Fotos de los empleados en una biblioteca de SharePoint (Graph simulado con httpx.MockTransport)."""
import httpx
import pytest

from app import fotos, microsoft
from app.config import settings
from app.database import SessionLocal
from app.models import Usuario
from app.seed import main as seed
from tests.test_sharepoint import super_login

seed()
URL = "https://otek.sharepoint.com/sites/GH/Documentos%20compartidos/Forms/AllItems.aspx"
IMAGEN = b"\xff\xd8\xff\xe0" + b"foto-de-prueba" * 50


@pytest.fixture
def graph(monkeypatch):
    for k, v in dict(microsoft_auth_enabled=True, microsoft_graph_enabled=True, microsoft_tenant_id="t",
                     microsoft_client_id="c", microsoft_client_secret="s", microsoft_authority_host="https://login.test",
                     microsoft_graph_url="https://graph.test/v1.0").items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(fotos, "SEGUNDO_PLANO", False)
    estado = {"archivos": {}, "carpetas": [], "borrados": [], "fallar_subida": False, "rutas": []}

    def manejador(req: httpx.Request):
        p, m = req.url.path, req.method
        if p.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "a.e30.b", "expires_in": 3600})
        if p == "/v1.0/sites/otek.sharepoint.com:/sites/GH":
            return httpx.Response(200, json={"id": "sitio1", "displayName": "Gestión Humana"})
        if p == "/v1.0/sites/sitio1/drives":
            return httpx.Response(200, json={"value": [
                {"id": "drv1", "name": "Documentos", "webUrl": "https://otek.sharepoint.com/sites/GH/Documentos%20compartidos"},
                {"id": "drv2", "name": "Otra", "webUrl": "https://otek.sharepoint.com/sites/GH/Otra"}]})
        if p.startswith("/v1.0/drives/drv1/") and p.endswith("/children") and m == "POST":
            import json
            estado["carpetas"].append(json.loads(req.content)["name"])
            return httpx.Response(201, json={"id": "carpeta1"})
        if p.startswith("/v1.0/drives/drv1/root:/") and p.endswith(":/content") and m == "PUT":
            if estado["fallar_subida"]:
                return httpx.Response(503, json={"error": {"message": "Servicio no disponible"}})
            n = f"it{len(estado['archivos']) + 1}"
            estado["archivos"][n] = req.content
            estado["rutas"].append(p)
            return httpx.Response(201, json={"id": n, "size": len(req.content)})
        if p.startswith("/v1.0/drives/drv1/items/") and p.endswith("/content"):
            n = p.split("/")[-2]
            if n not in estado["archivos"]:
                return httpx.Response(404)
            if m == "PUT":
                estado["archivos"][n] = req.content
                return httpx.Response(200, json={"id": n, "size": len(req.content)})
            return httpx.Response(200, content=estado["archivos"][n], headers={"content-type": "image/jpeg"})
        if p.startswith("/v1.0/drives/drv1/items/") and m == "DELETE":
            n = p.split("/")[-1]
            estado["borrados"].append(n)
            estado["archivos"].pop(n, None)
            return httpx.Response(204)
        if p == "/v1.0/users/ti.mexico@o-tek.com/drive":
            return httpx.Response(200, json={"id": "drv1", "name": "OneDrive",
                                             "webUrl": "https://otek-my.sharepoint.com/personal/ti_mexico_o-tek_com/Documents"})
        if p.startswith("/v1.0/users/") and "/photos/" in p:
            quien = p.split("/")[3]
            if quien in estado.get("fotos_ms", {}) and "432x432" in p:
                return httpx.Response(200, content=estado["fotos_ms"][quien], headers={"content-type": "image/jpeg"})
            return httpx.Response(404)
        return httpx.Response(404)
    microsoft.transporte = httpx.MockTransport(manejador)
    microsoft._token_app.update(valor=None, expira=0)
    yield estado
    microsoft.transporte = None
    microsoft._token_app.update(valor=None, expira=0)
    with SessionLocal() as db:
        fotos.guardar_config(db, None, None)


def _empleado(nomina="FS-1", nombre="Rosa María López Díaz") -> int:
    from datetime import date

    from app.security import password_inutilizable
    from app.sedes import sede_principal
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.numero_empleado == nomina).first()
        if not u:
            u = Usuario(numero_empleado=nomina, nombre=nombre, rol="planta", fecha_ingreso=date(2021, 1, 1),
                        password_hash=password_inutilizable(), sede_id=sede_principal(db).id, activo=True)
            db.add(u)
        u.foto, u.foto_tipo, u.foto_ref = IMAGEN, "image/jpeg", None
        db.commit()
        return u.id


def test_sin_biblioteca_la_foto_sigue_en_la_base(graph):
    adm = super_login()
    uid = _empleado("FS-0")
    assert adm.get("/api/fotos-sharepoint").json()["conectada"] is False
    r = adm.get(f"/api/usuarios/{uid}/foto")
    assert r.status_code == 200 and r.content == IMAGEN
    assert adm.post("/api/fotos-sharepoint/mover").status_code == 400


def test_conectar_mover_leer_y_quitar(graph):
    adm = super_login()
    uid = _empleado()
    r = adm.put("/api/fotos-sharepoint/conectar", json={"url": URL})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["drive_nombre"] == "Documentos" and d["carpeta"] == "Fotos SIP-O" and d["activo"] is False
    assert graph["carpetas"] == ["Fotos SIP-O"]
    assert d["en_servidor"] >= 1

    d = adm.put("/api/fotos-sharepoint/activo", json={"activo": True}).json()
    assert d["activo"] is True
    d = adm.post("/api/fotos-sharepoint/mover").json()
    assert d["movidas"] >= 1 and d["pendientes"] == 0 and not d["errores"]
    assert any("Fotos SIP-O/FS-1 - Rosa María López Díaz.jpg" in r for r in graph["rutas"])

    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        assert u.foto is None and u.foto_ref.startswith("drv1|") and u.foto_tipo == "image/jpeg"
        ref = u.foto_ref
    # Se descarga de SharePoint cuando no está en la memoria
    fotos._cache.clear()
    fotos._cache_bytes[0] = 0
    r = adm.get(f"/api/usuarios/{uid}/foto")
    assert r.status_code == 200 and r.content == IMAGEN
    assert ref in fotos._cache

    # Quitar la foto la manda a la papelera de SharePoint
    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        quitada = fotos.quitar(u)
        db.commit()
        fotos.tras_cambio(u, quitada)
    assert graph["borrados"] == [ref.split("|")[1]]
    assert adm.get(f"/api/usuarios/{uid}/foto").status_code == 404


def test_si_sharepoint_falla_la_foto_se_queda_en_el_servidor(graph):
    adm = super_login()
    adm.put("/api/fotos-sharepoint/conectar", json={"url": URL, "carpeta": "Gafetes/Fotos"})
    adm.put("/api/fotos-sharepoint/activo", json={"activo": True})
    uid = _empleado("FS-2", "Luis Pérez")
    graph["fallar_subida"] = True
    with SessionLocal() as db:
        fotos.tras_cambio(db.get(Usuario, uid))  # no lanza error
        u = db.get(Usuario, uid)
        db.refresh(u)
        assert u.foto == IMAGEN and u.foto_ref is None
    d = adm.post("/api/fotos-sharepoint/mover").json()
    assert d["movidas"] == 0 and d["errores"] and d["pendientes"] >= 1
    assert adm.get(f"/api/usuarios/{uid}/foto").content == IMAGEN
    graph["fallar_subida"] = False
    assert adm.post("/api/fotos-sharepoint/mover").json()["pendientes"] == 0


def test_url_de_carpeta_y_solo_superadmin(graph):
    from tests.test_api import login
    ana = login("ana@empresa.com", "Cambiar123")
    assert ana.get("/api/fotos-sharepoint").status_code == 403
    host, ruta = fotos._ruta_url("https://otek.sharepoint.com/sites/GH/Documentos%20compartidos/Forms/AllItems.aspx"
                                 "?id=%2Fsites%2FGH%2FDocumentos%20compartidos%2FRH%2FFotos&viewid=x")
    assert (host, ruta) == ("otek.sharepoint.com", "/sites/GH/Documentos compartidos/RH/Fotos")
    with pytest.raises(fotos.ErrorFotos):
        fotos._ruta_url("https://otro.com/sites/GH")


def test_actualizar_fotos_desde_microsoft(graph):
    adm = super_login()
    uid = _empleado("FS-3", "Marta Ruiz")
    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        u.microsoft_oid = "oid-marta"
        db.commit()
    nueva = b"JPG" + b"alta-resolucion" * 200
    graph["fotos_ms"] = {"oid-marta": nueva}
    desde, total = 0, {"actualizadas": 0, "iguales": 0}
    while True:
        r = adm.post("/api/fotos-sharepoint/actualizar-microsoft", json={"desde": desde})
        assert r.status_code == 200, r.text
        d = r.json()
        total["actualizadas"] += d["actualizadas"]
        if not d["siguiente"]:
            break
        desde = d["siguiente"]
    assert total["actualizadas"] >= 1
    assert adm.get(f"/api/usuarios/{uid}/foto").content == nueva
    # Sin cambios la segunda vez; con SharePoint activo, se sube y deja la base vacía
    adm.put("/api/fotos-sharepoint/conectar", json={"url": URL})
    adm.put("/api/fotos-sharepoint/activo", json={"activo": True})
    graph["fotos_ms"]["oid-marta"] = nueva + b"v2"
    d = adm.post("/api/fotos-sharepoint/actualizar-microsoft", json={"desde": uid - 1}).json()
    assert d["actualizadas"] == 1
    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        assert u.foto is None and u.foto_ref
    d = adm.post("/api/fotos-sharepoint/actualizar-microsoft", json={"desde": uid - 1}).json()
    assert d["actualizadas"] == 0 and d["iguales"] == 1


def test_onedrive_de_una_cuenta(graph):
    adm = super_login()
    r = adm.put("/api/fotos-sharepoint/conectar", json={"url": "TI.Mexico@o-tek.com"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["sitio_nombre"] == "OneDrive de ti.mexico@o-tek.com" and d["carpeta"] == "Fotos SIP-O"
    assert d["web_url"].endswith("/Documents/Fotos%20SIP-O")
