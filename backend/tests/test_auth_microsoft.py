"""Pruebas de integración del inicio de sesión con Microsoft, sesiones y Graph.

Microsoft se simula con httpx.MockTransport y una llave RSA real, de modo que se ejercita
todo el recorrido: redirección, PKCE, callback, validación del id_token, autorización local,
sesión en cookie, /me, persistencia, cierre de sesión y consulta de empleados en Graph.
"""
import base64
import hashlib
import json
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import microsoft
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Sesion, Usuario
from app.security import ahora, hash_password
from app.seed import main as seed

TENANT, CLIENT = "tenant-pruebas", "cliente-pruebas"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA_LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

MS: dict = {}  # estado del Microsoft simulado


def _jwk():
    pub = jwt.algorithms.RSAAlgorithm.to_jwk(LLAVE.public_key(), as_dict=True)
    return {**pub, "kid": "k1", "alg": "RS256", "use": "sig"}


def _id_token(**cambios):
    claims = {
        "iss": f"https://login.test/{TENANT}/v2.0", "aud": CLIENT, "tid": TENANT, "oid": "oid-ana",
        "preferred_username": "Ana@Empresa.com", "name": "Ana López", "nonce": MS.get("nonce"),
        "iat": int(time.time()), "exp": int(time.time()) + 600,
    }
    claims.update(cambios)
    llave = cambios.pop("_llave", None) or LLAVE
    claims.pop("_llave", None)
    return jwt.encode(claims, llave, algorithm="RS256", headers={"kid": "k1"})


def _manejador(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    if url.endswith("/discovery/v2.0/keys"):
        return httpx.Response(200, json={"keys": [_jwk()]})
    if url.endswith("/oauth2/v2.0/token"):
        form = parse_qs(req.content.decode())
        assert form["client_secret"] == ["secreto-pruebas"]
        if form["grant_type"] == ["client_credentials"]:
            return httpx.Response(200, json={"access_token": "token-app", "expires_in": 3600})
        # PKCE: el verifier debe corresponder al challenge enviado en la autorización
        verifier = form["code_verifier"][0]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if form["code"] != ["codigo-ok"] or challenge != MS["challenge"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"id_token": MS["id_token"](), "access_token": "token-usuario"})
    if url.startswith("https://graph.test/v1.0/"):
        ruta = url.split("/v1.0/", 1)[1]
        auth = req.headers.get("authorization")
        if ruta.startswith("me/photo"):
            assert auth == "Bearer token-usuario"
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        assert auth == "Bearer token-app"
        return MS["graph"](ruta)
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def microsoft_simulado():
    seed()
    anterior = {k: getattr(settings, k) for k in (
        "microsoft_auth_enabled", "microsoft_tenant_id", "microsoft_client_id", "microsoft_client_secret",
        "microsoft_graph_enabled", "microsoft_authority_host", "microsoft_graph_url", "password_login_roles")}
    settings.microsoft_auth_enabled = settings.microsoft_graph_enabled = True
    settings.microsoft_tenant_id, settings.microsoft_client_id = TENANT, CLIENT
    settings.microsoft_client_secret = "secreto-pruebas"
    settings.microsoft_authority_host = "https://login.test"
    settings.microsoft_graph_url = "https://graph.test/v1.0"
    microsoft.transporte = httpx.MockTransport(_manejador)
    microsoft._jwks.clear()
    microsoft._token_app.update(valor=None, expira=0)
    MS.clear()
    MS["id_token"] = _id_token
    yield
    for k, v in anterior.items():
        setattr(settings, k, v)
    microsoft.transporte = None


def _iniciar(c: TestClient, siguiente="/"):
    r = c.get(f"/api/auth/microsoft/login?next={siguiente}")
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "login.test" and url.path == f"/{TENANT}/oauth2/v2.0/authorize"
    assert q["client_id"] == CLIENT and q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == settings.microsoft_redirect_uri and "openid" in q["scope"]
    MS.update(nonce=q["nonce"], challenge=q["code_challenge"])
    return q["state"]


def _cliente():
    return TestClient(app, follow_redirects=False)


def test_recorrido_completo_login_me_persistencia_logout():
    c = _cliente()
    state = _iniciar(c, "/mi-equipo")
    r = c.get(f"/api/auth/microsoft/callback?code=codigo-ok&state={state}")
    assert r.status_code == 302 and r.headers["location"] == "/mi-equipo"
    assert "sip_session" in c.cookies and "token-usuario" not in r.text
    set_cookie = r.headers.get_list("set-cookie")
    assert any("sip_session" in h and "HttpOnly" in h and "samesite=lax" in h.lower() for h in set_cookie)

    me = c.get("/api/auth/me").json()
    assert me["authenticated"] and me["email"] == "ana@empresa.com" and me["auth_method"] == "microsoft"
    assert me["role"] == "oficina" and me["microsoft_vinculado"] and me["tiene_foto"]
    assert "vacaciones:solicitar" in me["permissions"]
    assert c.get("/api/auth/me").status_code == 200  # la sesión persiste entre peticiones (recarga)

    # El state es de un solo uso
    assert c.get(f"/api/auth/microsoft/callback?code=codigo-ok&state={state}").status_code == 400

    # Cerrar sesión: requiere CSRF; invalida la sesión local y devuelve la URL de cierre de Microsoft
    assert c.post("/api/auth/logout").status_code == 403
    r = c.post("/api/auth/logout", headers={"X-CSRF-Token": c.cookies["sip_csrf"]}).json()
    assert r["logout_url"].startswith(f"https://login.test/{TENANT}/oauth2/v2.0/logout?post_logout_redirect_uri=")
    assert c.get("/api/auth/me").status_code == 401


def test_usuario_no_registrado_403_sin_autorregistro():
    MS["id_token"] = lambda: _id_token(oid="oid-x", preferred_username="desconocido@empresa.com")
    c = _cliente()
    r = c.get(f"/api/auth/microsoft/callback?code=codigo-ok&state={_iniciar(c)}")
    assert r.status_code == 403 and "no está registrada" in r.text
    assert "sip_session" not in c.cookies
    with SessionLocal() as db:
        assert db.query(Usuario).filter(Usuario.email == "desconocido@empresa.com").count() == 0


def test_usuario_inactivo_403():
    with SessionLocal() as db:
        if not db.query(Usuario).filter(Usuario.email == "baja@empresa.com").first():
            db.add(Usuario(numero_empleado="9999", nombre="Baja", email="baja@empresa.com", rol="oficina",
                           password_hash=hash_password("Cambiar123"), fecha_ingreso=ahora().date(), activo=False))
            db.commit()
    MS["id_token"] = lambda: _id_token(oid="oid-baja", preferred_username="baja@empresa.com")
    c = _cliente()
    r = c.get(f"/api/auth/microsoft/callback?code=codigo-ok&state={_iniciar(c)}")
    assert r.status_code == 403 and "inactivo" in r.text


@pytest.mark.parametrize("cambios,esperado", [
    ({"aud": "otra-app"}, 401),                       # audience
    ({"iss": "https://login.test/otro/v2.0"}, 401),   # issuer
    ({"tid": "otro-tenant"}, 403),                    # tenant
    ({"nonce": "nonce-falso"}, 401),                  # nonce
    ({"exp": int(time.time()) - 3600}, 401),          # expirado
    ({"_llave": OTRA_LLAVE}, 401),                    # firma
])
def test_token_invalido_rechazado(cambios, esperado):
    MS["id_token"] = lambda: _id_token(**cambios)
    c = _cliente()
    r = c.get(f"/api/auth/microsoft/callback?code=codigo-ok&state={_iniciar(c)}")
    assert r.status_code == esperado and "sip_session" not in c.cookies


def test_state_de_otro_navegador_rechazado():
    atacante, victima = _cliente(), _cliente()
    state = _iniciar(atacante)
    _iniciar(victima)
    assert victima.get(f"/api/auth/microsoft/callback?code=codigo-ok&state={state}").status_code == 400


def test_cancelar_en_microsoft_y_redireccion_abierta():
    c = _cliente()
    r = c.get("/api/auth/microsoft/callback?error=access_denied&state=x")
    assert r.status_code == 302 and r.headers["location"] == "/login?error=cancelado"
    state = _iniciar(c, "//sitio-malicioso.com")
    r = c.get(f"/api/auth/microsoft/callback?code=codigo-ok&state={state}")
    assert r.headers["location"] == "/"


def test_sesion_expirada_y_csrf():
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"email": "carlos@empresa.com", "password": "Cambiar123"}).status_code == 200
    # Sin encabezado CSRF no se pueden modificar datos
    r = c.post("/api/permisos", json={"tipo": "llegada_tarde", "fecha": str(ahora().date() + timedelta(days=2)),
                                      "hora_inicio": "07:00", "hora_fin": "08:00"})
    assert r.status_code == 403 and "CSRF" in r.text
    with SessionLocal() as db:
        for s in db.query(Sesion).all():
            s.expira = ahora() - timedelta(minutes=1)
        db.commit()
    assert c.get("/api/auth/me").status_code == 401


def test_password_restringido_por_rol_y_alta_sin_password():
    settings.password_login_roles = "planta"
    c = TestClient(app)
    r = c.post("/api/auth/login-json", json={"email": "ana@empresa.com", "password": "Cambiar123"})
    assert r.status_code == 403 and "Microsoft" in r.text
    assert c.post("/api/auth/login-json", json={"email": "carlos@empresa.com", "password": "Cambiar123"}).status_code == 200
    settings.password_login_roles = ""


def _admin():
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"email": "admin@empresa.com", "password": "Admin123"}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def test_graph_prellena_alta_con_jefe_y_foto():
    def graph(ruta):
        if ruta.startswith("users/nuevo@empresa.com"):
            return httpx.Response(200, json={
                "id": "oid-nuevo", "displayName": "Pedro Nuevo", "mail": "Nuevo@Empresa.com", "jobTitle": "Analista",
                "department": "Finanzas", "employeeId": "3001", "employeeHireDate": "2023-05-02T00:00:00Z",
                "accountEnabled": True})
        if ruta.startswith("users/oid-nuevo/manager"):
            return httpx.Response(200, json={"displayName": "Laura Martínez", "mail": "laura@empresa.com"})
        if ruta.startswith("users/oid-nuevo/photos"):
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})
    MS["graph"] = graph
    admin = _admin()
    d = admin.get("/api/usuarios/microsoft/buscar?email=nuevo@empresa.com").json()
    assert d["nombre"] == "Pedro Nuevo" and d["email"] == "nuevo@empresa.com" and d["puesto"] == "Analista"
    assert d["numero_empleado"] == "3001" and d["fecha_ingreso"] == "2023-05-02"
    assert d["jefe"]["email"] == "laura@empresa.com" and d["jefe_id"] and d["foto"].startswith("data:image/png;base64,")

    # Alta sin contraseña (solo Microsoft) con la foto y el Object ID
    r = admin.post("/api/usuarios", json={
        "numero_empleado": d["numero_empleado"], "nombre": d["nombre"], "email": d["email"], "rol": "oficina",
        "fecha_ingreso": d["fecha_ingreso"], "puesto": d["puesto"], "departamento": d["departamento"],
        "jefe_id": d["jefe_id"], "microsoft_oid": d["oid"], "foto": d["foto"]})
    assert r.status_code == 201, r.text
    nuevo = r.json()
    assert nuevo["tiene_foto"] and nuevo["microsoft_vinculado"] and nuevo["jefe_nombre"] == "Laura Martínez"
    assert admin.get(f"/api/usuarios/{nuevo['id']}/foto").content == PNG
    assert TestClient(app).post("/api/auth/login-json", json={"email": "nuevo@empresa.com", "password": "x" * 8}).status_code == 401
    # Ya registrado
    assert admin.get("/api/usuarios/microsoft/buscar?email=nuevo@empresa.com").json()["ya_registrado_id"] == nuevo["id"]


def test_graph_registra_jefe_y_sugiere_es_jefe():
    def graph(ruta):
        if ruta.startswith("users/emp9@empresa.com"):
            return httpx.Response(200, json={"id": "oid-emp9", "displayName": "Empleado Nueve", "mail": "emp9@empresa.com",
                                             "jobTitle": "Analista", "accountEnabled": True})
        if ruta.startswith("users/oid-emp9/manager"):
            return httpx.Response(200, json={"id": "oid-jefe9", "displayName": "Jefa Nueve", "mail": "jefa9@empresa.com"})
        if ruta.startswith("users/jefa9@empresa.com"):
            return httpx.Response(200, json={"id": "oid-jefe9", "displayName": "Jefa Nueve", "mail": "jefa9@empresa.com",
                                             "jobTitle": "Gerente", "department": "Finanzas", "accountEnabled": True})
        if ruta.startswith("users/oid-jefe9/directReports"):
            return httpx.Response(200, json={"value": [{"id": "oid-emp9"}]})
        if "/directReports" in ruta:
            return httpx.Response(200, json={"value": []})
        return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})
    MS["graph"] = graph
    admin = _admin()
    d = admin.get("/api/usuarios/microsoft/buscar?email=emp9@empresa.com").json()
    assert d["jefe"]["nombre"] == "Jefa Nueve" and d["jefe_id"] is None and d["jefe_registrado_id"] is None
    assert d["tiene_reportes"] is False
    # Sin nómina en Microsoft hay que indicarla
    r = admin.post("/api/usuarios/microsoft/registrar-jefe", json={"email": "jefa9@empresa.com"})
    assert r.status_code == 422 and "nómina" in r.json()["detail"]
    r = admin.post("/api/usuarios/microsoft/registrar-jefe", json={"email": "jefa9@empresa.com", "numero_empleado": "J-9"})
    assert r.status_code == 200, r.text
    jefa = r.json()
    assert jefa["es_jefe"] and jefa["rol"] == "oficina" and jefa["puesto"] == "Gerente" and jefa["microsoft_vinculado"]
    # Ahora la búsqueda del empleado ya asigna a la jefa
    d = admin.get("/api/usuarios/microsoft/buscar?email=emp9@empresa.com").json()
    assert d["jefe_id"] == jefa["id"]
    assert admin.get("/api/usuarios/microsoft/buscar?email=jefa9@empresa.com").json()["tiene_reportes"] is True
    # Un usuario existente que no es jefe solo se marca como jefe
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.email == "jefa9@empresa.com").one()
        u.es_jefe = False
        db.commit()
    r = admin.post("/api/usuarios/microsoft/registrar-jefe", json={"email": "jefa9@empresa.com"})
    assert r.status_code == 200 and r.json()["es_jefe"] and r.json()["id"] == jefa["id"]


@pytest.mark.parametrize("respuesta,status,texto", [
    (httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}}), 404, "No existe"),
    (httpx.Response(403, json={"error": {"code": "Authorization_RequestDenied"}}), 502, "User.Read.All"),
])
def test_graph_errores_claros(respuesta, status, texto):
    MS["graph"] = lambda ruta: respuesta
    r = _admin().get("/api/usuarios/microsoft/buscar?email=x@empresa.com")
    assert r.status_code == status and texto in r.json()["detail"]


def test_health_sin_secretos():
    r = TestClient(app).get("/api/health")
    cuerpo = json.dumps(r.json())
    assert r.json()["microsoft_login_configurado"] is True
    assert "secreto-pruebas" not in cuerpo and CLIENT not in cuerpo and TENANT not in cuerpo
