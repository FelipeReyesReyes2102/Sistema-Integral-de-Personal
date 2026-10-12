"""Integración con Microsoft Entra ID (OpenID Connect) y Microsoft Graph.

- Inicio de sesión: Authorization Code Flow + PKCE, con el backend como cliente confidencial.
  El id_token se valida aquí (firma, issuer, audience, tenant, expiración y nonce).
- Graph (permiso de aplicación User.Read.All, client credentials): datos y foto de un empleado
  para ayudar a darlo de alta.

Nunca se registran tokens ni secretos en los logs.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import quote, urlencode

import httpx
import jwt

from .config import settings

log = logging.getLogger("sip.microsoft")

# Transporte HTTP inyectable (las pruebas lo reemplazan por un httpx.MockTransport)
transporte: httpx.BaseTransport | None = None


class ErrorMicrosoft(Exception):
    def __init__(self, codigo: str, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.status = codigo, mensaje, status


def _cliente() -> httpx.Client:
    return httpx.Client(transport=transporte, timeout=15)


def _authority() -> str:
    return f"{settings.microsoft_authority_host}/{settings.microsoft_tenant_id}"


def issuer_esperado() -> str:
    return f"{settings.microsoft_authority_host}/{settings.microsoft_tenant_id}/v2.0"


# ---------------- Authorization Code + PKCE ----------------
def nuevo_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def url_autorizacion(state: str, nonce: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri": settings.microsoft_redirect_uri,
        "response_mode": "query",
        "scope": settings.microsoft_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{_authority()}/oauth2/v2.0/authorize?{urlencode(params)}"


def url_cierre_sesion() -> str:
    destino = (f"{settings.microsoft_frontend_url.rstrip('/')}/login" if settings.microsoft_frontend_url
               else settings.microsoft_post_logout_redirect_uri)
    q = urlencode({"post_logout_redirect_uri": destino})
    return f"{_authority()}/oauth2/v2.0/logout?{q}"


def intercambiar_codigo(code: str, code_verifier: str) -> dict:
    data = {
        "client_id": settings.microsoft_client_id,
        "client_secret": settings.microsoft_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.microsoft_redirect_uri,
        "code_verifier": code_verifier,
        "scope": settings.microsoft_scopes,
    }
    try:
        with _cliente() as c:
            r = c.post(f"{_authority()}/oauth2/v2.0/token", data=data)
    except httpx.HTTPError as e:
        log.error("No se pudo contactar a Microsoft para canjear el código: %s", type(e).__name__)
        raise ErrorMicrosoft("red", "No se pudo contactar a Microsoft. Intenta de nuevo.", 502)
    if r.status_code != 200:
        error = _json(r).get("error", "desconocido")
        log.warning("Microsoft rechazó el canje del código: HTTP %s, error=%s", r.status_code, error)
        raise ErrorMicrosoft("canje", f"Microsoft rechazó el inicio de sesión ({error}).", 401)
    return r.json()


# ---------------- Validación del id_token ----------------
_jwks: dict[str, dict] = {}
_jwks_cargado = 0.0


def _llave(kid: str):
    global _jwks, _jwks_cargado
    if kid not in _jwks or time.time() - _jwks_cargado > 24 * 3600:
        with _cliente() as c:
            r = c.get(f"{_authority()}/discovery/v2.0/keys")
        r.raise_for_status()
        _jwks = {k["kid"]: k for k in r.json().get("keys", []) if "kid" in k}
        _jwks_cargado = time.time()
    if kid not in _jwks:
        raise ErrorMicrosoft("token", "La firma del token no corresponde a una llave de Microsoft.", 401)
    return jwt.PyJWK(_jwks[kid]).key


def validar_id_token(id_token: str, nonce: str) -> dict:
    try:
        kid = jwt.get_unverified_header(id_token).get("kid", "")
        claims = jwt.decode(
            id_token, _llave(kid), algorithms=["RS256"], audience=settings.microsoft_client_id,
            issuer=issuer_esperado(), leeway=60, options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except ErrorMicrosoft:
        raise
    except jwt.ExpiredSignatureError:
        raise ErrorMicrosoft("token", "El token de Microsoft expiró. Intenta de nuevo.", 401)
    except (jwt.PyJWTError, httpx.HTTPError) as e:
        log.warning("id_token inválido: %s", type(e).__name__)
        raise ErrorMicrosoft("token", "No se pudo validar la identidad devuelta por Microsoft.", 401)
    if claims.get("tid") != settings.microsoft_tenant_id:
        raise ErrorMicrosoft("tenant", "La cuenta no pertenece a la organización autorizada.", 403)
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ErrorMicrosoft("nonce", "La respuesta de Microsoft no corresponde a este inicio de sesión.", 401)
    return claims


def identidad(claims: dict) -> tuple[str | None, str, str]:
    """(oid, correo normalizado, nombre) a partir de los claims."""
    email = (claims.get("preferred_username") or claims.get("email") or claims.get("upn") or "").strip().lower()
    return claims.get("oid"), email, claims.get("name") or email


# ---------------- Microsoft Graph ----------------
_token_app = {"valor": None, "expira": 0.0}


def token_aplicacion() -> str:
    """Token de aplicación (client credentials) para Graph, en caché hasta poco antes de expirar."""
    if _token_app["valor"] and time.time() < _token_app["expira"] - 120:
        return _token_app["valor"]
    data = {
        "client_id": settings.microsoft_client_id,
        "client_secret": settings.microsoft_client_secret,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }
    try:
        with _cliente() as c:
            r = c.post(f"{_authority()}/oauth2/v2.0/token", data=data)
    except httpx.HTTPError as e:
        log.error("No se pudo obtener token de aplicación: %s", type(e).__name__)
        raise ErrorMicrosoft("red", "No se pudo contactar a Microsoft.", 502)
    if r.status_code != 200:
        error = _json(r).get("error", "desconocido")
        log.warning("Token de aplicación rechazado: HTTP %s, error=%s", r.status_code, error)
        raise ErrorMicrosoft("credenciales", "Las credenciales de la aplicación en Microsoft no son válidas "
                             f"({error}). Revisa el Client ID y el secreto.", 502)
    j = r.json()
    _token_app.update(valor=j["access_token"], expira=time.time() + int(j.get("expires_in", 3600)))
    return _token_app["valor"]



def roles_token(token: str) -> list[str]:
    """Permisos de aplicación (claim "roles") de un token de Graph. Solo lee la carga útil, no valida la firma:
    se usa únicamente para dar un mensaje de diagnóstico."""
    try:
        carga = token.split(".")[1]
        return list(json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4))).get("roles") or [])
    except (IndexError, ValueError, AttributeError):
        return []


def _graph(ruta: str, token: str) -> httpx.Response:
    with _cliente() as c:
        return c.get(f"{settings.microsoft_graph_url}/{ruta}", headers={"Authorization": f"Bearer {token}"})


def foto(token: str, sujeto: str = "me") -> tuple[bytes, str] | None:
    """Foto de perfil (96x96) o None si no tiene. `sujeto` = 'me' o 'users/{id}'."""
    try:
        r = _graph(f"{sujeto}/photos/96x96/$value", token)
        if r.status_code == 404:
            r = _graph(f"{sujeto}/photo/$value", token)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.content:
        return None
    return r.content, r.headers.get("content-type", "image/jpeg").split(";")[0]


def buscar_empleado(email: str) -> dict:
    """Datos del empleado en Entra ID para prellenar el alta."""
    token = token_aplicacion()
    campos = "id,displayName,mail,userPrincipalName,jobTitle,department,employeeId,employeeHireDate,accountEnabled"
    try:
        r = _graph(f"users/{quote(email.strip().lower(), safe='@.')}?$select={campos}", token)
    except httpx.HTTPError as e:
        log.error("Graph no respondió: %s", type(e).__name__)
        raise ErrorMicrosoft("red", "Microsoft Graph no respondió.", 502)
    if r.status_code == 404:
        raise ErrorMicrosoft("no_encontrado", f"No existe una cuenta de Microsoft con el correo {email}.", 404)
    if r.status_code == 401:
        _token_app["valor"] = None
        raise ErrorMicrosoft("no_autorizado", "Microsoft rechazó el token de la aplicación; intenta de nuevo.", 502)
    if r.status_code == 403:
        codigo = _json(r).get("error", {}).get("code", "accessDenied")
        log.warning("Graph accessDenied al consultar usuarios (%s)", codigo)
        raise ErrorMicrosoft("sin_permiso", "La aplicación no tiene el permiso User.Read.All con consentimiento "
                             "de administrador en Microsoft Entra ID.", 502)
    if r.status_code != 200:
        log.warning("Graph devolvió HTTP %s al consultar usuario", r.status_code)
        raise ErrorMicrosoft("graph", f"Microsoft Graph devolvió un error ({r.status_code}).", 502)
    u = r.json()
    jefe = None
    try:
        rm = _graph(f"users/{u['id']}/manager?$select=id,displayName,mail,userPrincipalName,jobTitle", token)
        if rm.status_code == 200:
            m = rm.json()
            jefe = {"nombre": m.get("displayName"), "email": (m.get("mail") or m.get("userPrincipalName") or "").lower(),
                    "oid": m.get("id"), "puesto": m.get("jobTitle")}
    except httpx.HTTPError:
        pass
    # Si tiene personas a cargo en Microsoft, se sugiere marcarlo como jefe
    tiene_reportes = False
    try:
        rr = _graph(f"users/{u['id']}/directReports?$top=1&$select=id", token)
        tiene_reportes = rr.status_code == 200 and bool(_json(rr).get("value"))
    except httpx.HTTPError:
        pass
    imagen = foto(token, f"users/{u['id']}")
    contratacion = (u.get("employeeHireDate") or "")[:10] or None
    return {
        "oid": u["id"],
        "nombre": u.get("displayName"),
        "email": (u.get("mail") or u.get("userPrincipalName") or email).lower(),
        "puesto": u.get("jobTitle"),
        "departamento": u.get("department"),
        "numero_empleado": u.get("employeeId"),
        "fecha_ingreso": contratacion,
        "cuenta_habilitada": u.get("accountEnabled", True),
        "jefe": jefe,
        "tiene_reportes": tiene_reportes,
        "foto": f"data:{imagen[1]};base64,{base64.b64encode(imagen[0]).decode()}" if imagen else None,
    }


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}


# ---------------- Prueba de conexión (pantalla de Configuración) ----------------
def _codigo_aadsts(r: httpx.Response) -> str:
    j = _json(r)
    codigos = j.get("error_codes") or []
    return f"{j.get('error', 'error')}{f' (AADSTS{codigos[0]})' if codigos else ''}"


def probar_conexion() -> list[dict]:
    """Verifica tenant, Client ID/secreto, permiso de Graph y URI de redirección. No expone secretos."""
    res: list[dict] = []

    def agregar(nombre: str, estado: str, detalle: str):
        res.append({"nombre": nombre, "estado": estado, "detalle": detalle})

    s = settings
    if not s.microsoft_tenant_id:
        agregar("Inquilino (tenant)", "error", "Falta el Id. del directorio.")
        return res
    try:
        with _cliente() as c:
            r = c.get(f"{_authority()}/v2.0/.well-known/openid-configuration")
        if r.status_code == 200:
            agregar("Inquilino (tenant)", "ok", "Microsoft reconoce el directorio.")
        else:
            agregar("Inquilino (tenant)", "error", f"Microsoft no reconoce el directorio: {_codigo_aadsts(r)}.")
            return res
    except httpx.HTTPError as e:
        agregar("Inquilino (tenant)", "error", f"No se pudo contactar a Microsoft ({type(e).__name__}).")
        return res

    if not s.microsoft_client_id or not s.microsoft_client_secret:
        agregar("Aplicación y secreto", "error", "Falta el Id. de aplicación o el secreto de cliente.")
        return res
    data = {"client_id": s.microsoft_client_id, "client_secret": s.microsoft_client_secret,
            "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"}
    with _cliente() as c:
        r = c.post(f"{_authority()}/oauth2/v2.0/token", data=data)
    if r.status_code != 200:
        error = _json(r).get("error", "")
        motivo = {
            "invalid_client": "El secreto es incorrecto o ya venció.",
            "unauthorized_client": "El Id. de aplicación no existe en este directorio.",
            "invalid_request": "La solicitud no es válida; revisa el Id. de aplicación.",
        }.get(error, "Microsoft rechazó las credenciales.")
        agregar("Aplicación y secreto", "error", f"{motivo} [{_codigo_aadsts(r)}]")
        return res
    agregar("Aplicación y secreto", "ok", "El Id. de aplicación y el secreto son válidos.")
    token = r.json().get("access_token", "")

    if s.microsoft_graph_enabled:
        rg = _graph("users?$top=1&$select=id", token)
        if rg.status_code == 200:
            agregar("Consulta de empleados (Graph)", "ok", "Permiso User.Read.All concedido.")
        elif rg.status_code == 403:
            agregar("Consulta de empleados (Graph)", "error",
                    "Falta el permiso de aplicación User.Read.All con consentimiento de administrador.")
        else:
            agregar("Consulta de empleados (Graph)", "error", f"Graph respondió HTTP {rg.status_code}.")
    else:
        agregar("Consulta de empleados (Graph)", "omitido", "Deshabilitada: no se cargarán datos ni fotos al dar de alta.")

    uri = s.microsoft_redirect_uri or ""
    local = uri.startswith(("http://localhost", "http://127.0.0.1"))
    if not uri.endswith("/api/auth/microsoft/callback"):
        agregar("URI de redirección", "error", "Debe terminar en /api/auth/microsoft/callback.")
    elif not uri.startswith("https://") and not local:
        agregar("URI de redirección", "error", "En producción debe usar https://.")
    else:
        agregar("URI de redirección", "aviso",
                f"Confirma que {uri} esté registrada en Entra ID como plataforma Web (Microsoft no permite verificarlo).")
    if not s.microsoft_auth_enabled:
        agregar("Inicio de sesión", "aviso", "La autenticación con Microsoft está deshabilitada; actívala para usarla.")
    return res
