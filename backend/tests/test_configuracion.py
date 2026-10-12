"""Configuración de Microsoft desde la aplicación: validación, secreto cifrado, bloqueo y prueba de conexión."""
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app import microsoft
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import ConfiguracionApp, Usuario
from app.security import hash_password
from app.seed import main as seed

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENTE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRETO = "s3cr3to~de~prueba"


def _cliente(email, pwd):
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"email": email, "password": pwd}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def _datos(**cambios):
    d = {
        "microsoft_auth_enabled": True, "microsoft_tenant_id": TENANT, "microsoft_client_id": CLIENTE,
        "microsoft_client_secret": SECRETO, "microsoft_redirect_uri": "https://vacaciones.o-tek.com/api/auth/microsoft/callback",
        "microsoft_frontend_url": "https://vacaciones.o-tek.com", "microsoft_scopes": "openid profile email User.Read",
        "microsoft_graph_enabled": True, "password_login_enabled": True, "password_login_roles": "",
    }
    d.update(cambios)
    return d


def crear_super():
    with SessionLocal() as db:
        if not db.query(Usuario).filter(Usuario.email == "super@empresa.com").first():
            db.add(Usuario(numero_empleado="SA-T1", nombre="Super Pruebas", email="super@empresa.com", rol="superadmin",
                           password_hash=hash_password("Super12345"), fecha_ingreso=date(2020, 1, 1)))
            db.commit()


@pytest.fixture
def admin():
    """Solo un super administrador puede configurar Microsoft."""
    seed()
    crear_super()
    c = _cliente("super@empresa.com", "Super12345")
    yield c
    c.delete("/api/admin/config/microsoft")  # restaurar .env para las demás pruebas
    microsoft.transporte = None


def test_guardar_cifra_secreto_y_no_lo_devuelve(admin):
    r = admin.put("/api/admin/config/microsoft", json=_datos())
    assert r.status_code == 200, r.text
    assert SECRETO not in r.text and r.json()["secreto_configurado"]
    assert r.json()["origen"]["MICROSOFT_TENANT_ID"] == "configuracion"
    assert r.json()["microsoft_login_configurado"] and settings.microsoft_client_secret == SECRETO
    with SessionLocal() as db:
        fila = db.get(ConfiguracionApp, "MICROSOFT_CLIENT_SECRET")
        assert fila.cifrado and SECRETO not in fila.valor
    # Guardar sin secreto conserva el anterior
    r = admin.put("/api/admin/config/microsoft", json=_datos(microsoft_client_secret=None, microsoft_tenant_id="o-tek.onmicrosoft.com"))
    assert r.status_code == 200 and r.json()["secreto_configurado"] and settings.microsoft_tenant_id == "o-tek.onmicrosoft.com"
    # La URL de cierre de sesión usa la URL pública
    assert "vacaciones.o-tek.com%2Flogin" in microsoft.url_cierre_sesion()
    # Volver a .env
    r = admin.delete("/api/admin/config/microsoft").json()
    assert not r["secreto_configurado"] and r["origen"]["MICROSOFT_TENANT_ID"] == "env"


@pytest.mark.parametrize("cambios,texto", [
    ({"microsoft_tenant_id": "no es valido"}, "GUID o un dominio"),
    ({"microsoft_client_id": "123"}, "Id. de aplicación"),
    ({"microsoft_redirect_uri": "https://x.com/otra"}, "/api/auth/microsoft/callback"),
    ({"microsoft_scopes": "profile"}, "openid"),
    ({"password_login_roles": "jefes"}, "Roles no válidos"),
    ({"microsoft_client_secret": None, "microsoft_client_id": ""}, "se requieren"),
])
def test_validaciones(admin, cambios, texto):
    r = admin.put("/api/admin/config/microsoft", json=_datos(**cambios))
    assert r.status_code == 422 and texto in r.json()["detail"]


def test_no_deja_al_admin_sin_acceso(admin):
    for cambios in ({"password_login_roles": "planta"}, {"password_login_enabled": False}):
        r = admin.put("/api/admin/config/microsoft", json=_datos(**cambios))
        assert r.status_code == 422 and "inicia sesión con" in r.json()["detail"]
    assert admin.put("/api/admin/config/microsoft", json=_datos(password_login_roles="planta,superadmin")).status_code == 200


def test_solo_super_administrador():
    seed()
    for email, pwd in (("ana@empresa.com", "Cambiar123"), ("admin@empresa.com", "Admin123")):
        c = _cliente(email, pwd)
        assert c.get("/api/admin/config/microsoft").status_code == 403
        assert c.put("/api/admin/config/microsoft", json=_datos()).status_code == 403


def test_probar_conexion_informa_secreto_incorrecto(admin):
    def manejador(req: httpx.Request):
        if req.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": "x"})
        if req.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(401, json={"error": "invalid_client", "error_codes": [7000215]})
        return httpx.Response(404)
    microsoft.transporte = httpx.MockTransport(manejador)
    admin.put("/api/admin/config/microsoft", json=_datos())
    res = admin.post("/api/admin/config/microsoft/probar").json()["resultados"]
    assert res[0]["estado"] == "ok"
    assert res[1]["estado"] == "error" and "secreto" in res[1]["detalle"] and "7000215" in res[1]["detalle"]
    assert SECRETO not in str(res)


def test_probar_conexion_completa(admin):
    def manejador(req: httpx.Request):
        if req.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={})
        if req.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "graph.microsoft.com" in str(req.url):
            return httpx.Response(403, json={"error": {"code": "Authorization_RequestDenied"}})
        return httpx.Response(404)
    microsoft.transporte = httpx.MockTransport(manejador)
    admin.put("/api/admin/config/microsoft", json=_datos())
    res = {r["nombre"]: r for r in admin.post("/api/admin/config/microsoft/probar").json()["resultados"]}
    assert res["Aplicación y secreto"]["estado"] == "ok"
    assert res["Consulta de empleados (Graph)"]["estado"] == "error" and "User.Read.All" in res["Consulta de empleados (Graph)"]["detalle"]
    assert res["URI de redirección"]["estado"] == "aviso"
