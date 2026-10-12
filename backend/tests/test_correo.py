"""Avisos por correo a caseta: configuración, envío al autorizar/cancelar, errores, reintento y Graph."""
import smtplib
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import correo, microsoft
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import ConfiguracionApp
from app.seed import main as seed

FIRMA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
ENVIADOS: list = []
FALLA = {"activa": False}


class SMTPFalso:
    """Servidor SMTP simulado: guarda los mensajes en ENVIADOS."""
    def __init__(self, host, puerto, timeout=None, context=None):
        self.host, self.puerto = host, puerto

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, usuario, password):
        if FALLA["activa"]:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        assert password == "clave-smtp"

    def send_message(self, msg):
        ENVIADOS.append(msg)


def entrar(email, pwd="Cambiar123"):
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": email, "password": pwd}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


CONFIG = {"caseta_activo": True, "caseta_destinatarios": "caseta1@o-tek.com, caseta2@o-tek.com",
          "caseta_tipos": ["llegada_tarde", "salida_temprana", "salida_intermedia"], "metodo": "smtp",
          "remitente": "avisos@o-tek.com", "remitente_nombre": "SIP-O", "smtp_host": "smtp.o-tek.com",
          "smtp_puerto": 587, "smtp_seguridad": "starttls", "smtp_usuario": "avisos@o-tek.com",
          "smtp_password": "clave-smtp"}


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    seed()
    monkeypatch.setattr(correo.smtplib, "SMTP", SMTPFalso)
    ENVIADOS.clear()
    FALLA["activa"] = False
    yield
    with SessionLocal() as db:
        correo.guardar(db, {k: None for k in correo.CLAVES}, None)
    microsoft.transporte = None


def permiso_de_carlos(tipo="salida_temprana", dias=3):
    carlos = entrar("carlos@empresa.com")
    fecha = date.today() + timedelta(days=dias)
    datos = {"tipo": tipo, "fecha": str(fecha), "motivo": "Trámite", "tipo_nomina": "con_goce", "firma": FIRMA, "enviar": True}
    if tipo == "home_office":
        datos["fecha_fin"] = str(fecha + timedelta(days=2))
    else:
        datos.update(hora_inicio="15:00", hora_fin="19:00")
    r = carlos.post("/api/permisos", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def test_configuracion_validaciones_y_secreto():
    admin = entrar("admin@empresa.com", "Admin123")
    r = admin.put("/api/admin/correo", json={**CONFIG, "caseta_destinatarios": ""})
    assert r.status_code == 422 and "caseta" in r.text
    assert admin.put("/api/admin/correo", json={**CONFIG, "caseta_destinatarios": "no-es-correo"}).status_code == 422
    r = admin.put("/api/admin/correo", json=CONFIG)
    assert r.status_code == 200 and "clave-smtp" not in r.text and r.json()["password_configurada"]
    with SessionLocal() as db:
        fila = db.get(ConfiguracionApp, "CORREO_SMTP_PASSWORD")
        assert fila.cifrado and "clave-smtp" not in fila.valor
    assert entrar("ana@empresa.com").get("/api/admin/correo").status_code == 403


def test_aviso_a_caseta_al_autorizar_y_al_cancelar():
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/admin/correo", json=CONFIG)
    p = permiso_de_carlos()
    laura = entrar("laura@empresa.com")
    assert laura.post(f"/api/permisos/{p['id']}/validar", json={}).json()["estado"] == "validado"
    assert len(ENVIADOS) == 1
    msg = ENVIADOS[0]
    assert "Autorizado" in msg["Subject"] and "Carlos Pérez" in msg["Subject"]
    assert msg["To"] == "caseta1@o-tek.com, caseta2@o-tek.com"
    cuerpo = msg.get_body(("plain",)).get_content()
    assert "2001" in cuerpo and "15:00 a 19:00" in cuerpo and "Laura Martínez" in cuerpo
    hist = admin.get("/api/admin/correo/historial").json()
    assert hist[0]["estado"] == "enviado" and hist[0]["empleado"] == "Carlos Pérez"

    # Cancelación de un permiso ya autorizado: también se avisa
    admin.post(f"/api/permisos/{p['id']}/cancelar")
    assert len(ENVIADOS) == 2 and "Cancelado" in ENVIADOS[1]["Subject"]


def test_tipos_no_seleccionados_no_avisan():
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/admin/correo", json=CONFIG)  # home office no está en los tipos
    p = permiso_de_carlos("home_office", dias=40)
    entrar("laura@empresa.com").post(f"/api/permisos/{p['id']}/validar", json={})
    assert ENVIADOS == []


def test_error_de_envio_no_bloquea_y_se_puede_reintentar():
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/admin/correo", json=CONFIG)
    FALLA["activa"] = True
    p = permiso_de_carlos("llegada_tarde", dias=5)
    r = entrar("laura@empresa.com").post(f"/api/permisos/{p['id']}/validar", json={})
    assert r.json()["estado"] == "validado"  # la autorización no depende del correo
    n = admin.get("/api/admin/correo/historial").json()[0]
    assert n["estado"] == "error" and "usuario o la contraseña" in n["error"]
    FALLA["activa"] = False
    assert admin.post(f"/api/admin/correo/historial/{n['id']}/reintentar").json()["ok"] is True
    assert len(ENVIADOS) == 1


def test_correo_de_prueba():
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/admin/correo", json=CONFIG)
    r = admin.post("/api/admin/correo/prueba", json={"destinatario": "yo@o-tek.com"}).json()
    assert r["ok"] and ENVIADOS[0]["To"] == "yo@o-tek.com" and "prueba" in ENVIADOS[0]["Subject"]


def test_envio_por_microsoft_365(monkeypatch):
    for k, v in dict(microsoft_auth_enabled=True, microsoft_graph_enabled=True, microsoft_tenant_id="t",
                     microsoft_client_id="c", microsoft_client_secret="s",
                     microsoft_authority_host="https://login.test", microsoft_graph_url="https://graph.test/v1.0").items():
        monkeypatch.setattr(settings, k, v)
    enviados = []

    def manejador(req: httpx.Request):
        if req.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if req.url.path.endswith("/sendMail"):
            enviados.append(req.url.path)
            return httpx.Response(202) if "avisos@" in req.url.path else httpx.Response(403)
        return httpx.Response(404)
    microsoft.transporte = httpx.MockTransport(manejador)
    microsoft._token_app.update(valor=None, expira=0)
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/admin/correo", json={**CONFIG, "metodo": "graph"})
    assert admin.post("/api/admin/correo/prueba", json={}).json()["ok"] is True
    assert enviados == ["/v1.0/users/avisos@o-tek.com/sendMail"]
    admin.put("/api/admin/correo", json={**CONFIG, "metodo": "graph", "remitente": "otro@o-tek.com"})
    r = admin.post("/api/admin/correo/prueba", json={}).json()
    assert r["ok"] is False and "Mail.Send" in r["error"]


def test_graph_renueva_token_en_cache_sin_mail_send(monkeypatch):
    """Si el token en caché se emitió antes del consentimiento, un 403 provoca pedir un token nuevo y reintentar."""
    for k, v in dict(microsoft_auth_enabled=True, microsoft_graph_enabled=True, microsoft_tenant_id="t",
                     microsoft_client_id="c", microsoft_client_secret="s",
                     microsoft_authority_host="https://login.test", microsoft_graph_url="https://graph.test/v1.0").items():
        monkeypatch.setattr(settings, k, v)
    llamadas = []

    def manejador(req: httpx.Request):
        if req.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "nuevo", "expires_in": 3600})
        if req.url.path.endswith("/sendMail"):
            llamadas.append(req.headers["Authorization"])
            if req.headers["Authorization"] == "Bearer viejo":
                return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}})
            return httpx.Response(202)
        return httpx.Response(404)
    microsoft.transporte = httpx.MockTransport(manejador)
    microsoft._token_app.update(valor="viejo", expira=9e12)
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put("/api/admin/correo", json={**CONFIG, "metodo": "graph"})
    assert admin.post("/api/admin/correo/prueba", json={}).json()["ok"] is True
    assert llamadas == ["Bearer viejo", "Bearer nuevo"]
