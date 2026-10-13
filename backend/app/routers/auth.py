"""Autenticación: usuario/contraseña y Microsoft Entra ID, con sesión en cookie HttpOnly."""
import html
import hmac
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, object_session

from .. import microsoft
from ..config import settings
from ..database import get_db
from ..models import FlujoOAuth, Usuario
from ..schemas import CambioPassword, LoginIn, MeOut
from ..security import (
    poner_cookie_csrf,
    MAX_INTENTOS, MINUTOS_BLOQUEO, ahora, auditar, borrar_cookies, cerrar_sesion, crear_sesion, get_current_user,
    hash_password, permisos_de,
    puede_usar_password, sesion_actual, verify_password,
)
from ..services import usuario_out
from ..sedes import sedes_visibles

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_STATE = "sip_oauth_state"
RUTA_CALLBACK = "/api/auth/microsoft"
VIGENCIA_FLUJO = timedelta(minutes=10)

MENSAJES = {
    "no_registrado": "Tu cuenta de Microsoft no está registrada en el sistema. Pide al administrador que te dé de alta.",
    "inactivo": "Tu usuario está inactivo. Contacta al administrador.",
    "cuenta_distinta": "Este correo está vinculado a otra cuenta de Microsoft. Contacta al administrador.",
    "estado_invalido": "La solicitud de inicio de sesión expiró o no es válida. Intenta de nuevo.",
    "cancelado": "Se canceló el inicio de sesión con Microsoft.",
    "no_configurado": "El inicio de sesión con Microsoft no está configurado.",
}


def me_out(user: Usuario, metodo: str | None) -> MeOut:
    base = usuario_out(user).model_dump()
    db = object_session(user)
    sedes = [{"id": s.id, "nombre": s.nombre, "zona_horaria": s.zona_horaria} for s in sedes_visibles(db, user)] if db else []
    return MeOut(**base, authenticated=True, display_name=user.nombre, role=user.rol, auth_method=metodo,
                 permissions=permisos_de(user), puede_usar_password=puede_usar_password(user), sedes=sedes)


@router.get("/config")
def config_publica():
    """Configuración pública para la pantalla de inicio de sesión (sin credenciales)."""
    return {
        "app_nombre": settings.app_nombre,
        "app_descripcion": settings.app_descripcion,
        "microsoft": settings.microsoft_configurado,
        "password_login": settings.password_login_enabled,
    }


# ---------------- Usuario y contraseña ----------------
@router.post("/login-json", response_model=MeOut)
def login_password(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not settings.password_login_enabled:
        raise HTTPException(403, "El acceso con contraseña está deshabilitado; usa tu cuenta de Microsoft.")
    ident = (data.usuario or data.email or "").strip()
    if "@" in ident:  # correo corporativo o personal
        user = db.scalar(select(Usuario).where(func.lower(Usuario.email) == ident.lower())) or             db.scalar(select(Usuario).where(func.lower(Usuario.email_personal) == ident.lower()))
    else:             # número de nómina
        user = db.scalar(select(Usuario).where(func.lower(Usuario.numero_empleado) == ident.lower())) if ident else None
    t = ahora()
    if user and user.bloqueado_hasta and user.bloqueado_hasta > t:
        minutos = max(1, int((user.bloqueado_hasta - t).total_seconds() // 60) + 1)
        raise HTTPException(423, f"Usuario bloqueado por intentos fallidos. Intenta de nuevo en {minutos} minuto(s) "
                                 "o pide al administrador que restablezca tu contraseña.")
    if not user or not user.activo or not verify_password(data.password, user.password_hash):
        if user:
            user.intentos_fallidos = (user.intentos_fallidos or 0) + 1
            if user.intentos_fallidos >= MAX_INTENTOS:
                user.bloqueado_hasta, user.intentos_fallidos = t + timedelta(minutes=MINUTOS_BLOQUEO), 0
                auditar(db, "usuario_bloqueado", usuario_id=user.id, detalle=f"{MAX_INTENTOS} intentos fallidos", request=request)
        auditar(db, "login_fallido", usuario_id=user.id if user else None, detalle=f"password · {ident[:80]}", request=request)
        db.commit()
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    if not puede_usar_password(user):
        raise HTTPException(403, "Tu usuario debe iniciar sesión con su cuenta de Microsoft.")
    if user.debe_cambiar_password and user.password_temporal_expira and user.password_temporal_expira < t:
        raise HTTPException(401, "Tu contraseña temporal venció. Pide al administrador una nueva.")
    user.intentos_fallidos, user.bloqueado_hasta = 0, None
    crear_sesion(db, response, user, "password", request)
    auditar(db, "login", usuario_id=user.id, detalle="password", request=request)
    db.commit()
    return me_out(user, "password")


# ---------------- Microsoft Entra ID ----------------
def _siguiente_seguro(siguiente: str | None) -> str:
    """Solo rutas internas (evita redirecciones abiertas)."""
    if not siguiente or not siguiente.startswith("/") or siguiente.startswith("//") or "\\" in siguiente:
        return "/"
    return siguiente[:255]


@router.get("/microsoft/login")
def microsoft_login(next: str | None = None, db: Session = Depends(get_db)):
    """Inicia Authorization Code + PKCE: guarda state/nonce/verifier y redirige a Microsoft."""
    if not settings.microsoft_configurado:
        return RedirectResponse("/login?error=no_configurado", 302)
    db.execute(delete(FlujoOAuth).where(FlujoOAuth.creado < ahora() - VIGENCIA_FLUJO))
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = microsoft.nuevo_pkce()
    db.add(FlujoOAuth(state=state, nonce=nonce, code_verifier=verifier, siguiente=_siguiente_seguro(next), creado=ahora()))
    db.commit()
    resp = RedirectResponse(microsoft.url_autorizacion(state, nonce, challenge), 302)
    resp.set_cookie(COOKIE_STATE, state, max_age=int(VIGENCIA_FLUJO.total_seconds()), httponly=True,
                    secure=settings.session_cookie_secure, samesite="lax", path=RUTA_CALLBACK)
    return resp


def _rechazo(codigo: str, status: int, mensaje: str | None = None) -> HTMLResponse:
    """Página 403/400 con mensaje claro y enlace de regreso al inicio de sesión."""
    texto = html.escape(mensaje or MENSAJES.get(codigo, "No fue posible iniciar sesión."))
    destino = f"/login?error={codigo}"
    cuerpo = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Acceso no permitido</title>
<style>body{{font-family:Inter,system-ui,sans-serif;background:#f4f6fa;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px}}
.c{{background:#161e2f;color:#fff;border-radius:10px;padding:32px;max-width:420px;text-align:center}}
a{{display:inline-block;margin-top:18px;background:#1f4a86;color:#fff;padding:10px 18px;border-radius:4px;text-decoration:none}}</style>
</head><body><div class="c"><h2>No fue posible iniciar sesión</h2><p>{texto}</p>
<a href="{destino}">Volver al inicio de sesión</a></div></body></html>"""
    resp = HTMLResponse(cuerpo, status_code=status)
    resp.delete_cookie(COOKIE_STATE, path=RUTA_CALLBACK)
    return resp


@router.get("/microsoft/callback")
def microsoft_callback(request: Request, code: str | None = None, state: str | None = None,
                       error: str | None = None, db: Session = Depends(get_db)):
    if error:
        auditar(db, "login_rechazado", detalle=f"microsoft · error={error[:60]}", request=request)
        db.commit()
        codigo = "cancelado" if error == "access_denied" else "estado_invalido"
        return RedirectResponse(f"/login?error={codigo}", 302)
    if not settings.microsoft_configurado:
        return _rechazo("no_configurado", 400)

    # state: debe coincidir con la cookie del navegador y existir (un solo uso, 10 minutos)
    cookie_state = request.cookies.get(COOKIE_STATE, "")
    flujo = db.get(FlujoOAuth, state) if state else None
    if flujo:
        db.delete(flujo)
        db.commit()
    if (not code or not flujo or not hmac.compare_digest(cookie_state, state or "")
            or flujo.creado < ahora() - VIGENCIA_FLUJO):
        return _rechazo("estado_invalido", 400)

    try:
        tokens = microsoft.intercambiar_codigo(code, flujo.code_verifier)
        claims = microsoft.validar_id_token(tokens.get("id_token", ""), flujo.nonce)
    except microsoft.ErrorMicrosoft as e:
        auditar(db, "login_rechazado", detalle=f"microsoft · {e.codigo}", request=request)
        db.commit()
        return _rechazo(e.codigo, 403 if e.status == 403 else 401, e.mensaje)

    oid, email, _nombre = microsoft.identidad(claims)
    user = db.scalar(select(Usuario).where(Usuario.microsoft_oid == oid)) if oid else None
    if user is None and email:
        user = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))
        if user is not None and user.microsoft_oid and user.microsoft_oid != oid:
            auditar(db, "login_rechazado", usuario_id=user.id, detalle="microsoft · oid distinto", request=request)
            db.commit()
            return _rechazo("cuenta_distinta", 403)
    if user is None:
        auditar(db, "login_rechazado", detalle=f"microsoft · no registrado · {email}", request=request)
        db.commit()
        return _rechazo("no_registrado", 403)
    if not user.activo:
        auditar(db, "login_rechazado", usuario_id=user.id, detalle="microsoft · inactivo", request=request)
        db.commit()
        return _rechazo("inactivo", 403)

    if not user.microsoft_oid and oid:
        user.microsoft_oid = oid
        auditar(db, "microsoft_vinculado", usuario_id=user.id, request=request)
    if user.foto_tipo is None and tokens.get("access_token") and "User.Read" in settings.microsoft_scopes:
        imagen = microsoft.foto(tokens["access_token"])  # mejor esfuerzo; no bloquea el acceso
        if imagen:
            user.foto, user.foto_tipo = imagen

    resp = RedirectResponse(flujo.siguiente or "/", 302)
    resp.delete_cookie(COOKIE_STATE, path=RUTA_CALLBACK)
    crear_sesion(db, resp, user, "microsoft", request)
    auditar(db, "login", usuario_id=user.id, detalle="microsoft", request=request)
    db.commit()
    return resp


# ---------------- Sesión ----------------
@router.get("/me", response_model=MeOut)
def me(request: Request, response: Response, user: Usuario = Depends(get_current_user)):
    sesion = getattr(request.state, "sesion", None)
    # Si el navegador perdió la cookie CSRF pero la sesión sigue válida, se vuelve a emitir para no dejar
    # al usuario sin poder guardar nada ("Token CSRF inválido") hasta que cierre sesión.
    if sesion and request.cookies.get(settings.csrf_cookie_name) != sesion.csrf:
        poner_cookie_csrf(response, sesion.csrf)
    return me_out(user, sesion and sesion.metodo)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Cierra la sesión local y, si se entró con Microsoft, devuelve la URL para cerrar la de Microsoft."""
    sesion = sesion_actual(request, db)
    if sesion and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), sesion.csrf):
        raise HTTPException(403, "Token CSRF inválido; recarga la página")
    metodo = sesion.metodo if sesion else None
    if sesion:
        auditar(db, "logout", usuario_id=sesion.usuario_id, request=request)
        cerrar_sesion(request, db)
    borrar_cookies(response)
    url = microsoft.url_cierre_sesion() if metodo == "microsoft" and settings.microsoft_configurado else None
    return {"ok": True, "logout_url": url}


@router.post("/cambiar-password", status_code=204)
def cambiar_password(data: CambioPassword, request: Request, user: Usuario = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if not puede_usar_password(user):
        raise HTTPException(400, "Tu usuario entra con Microsoft; la contraseña se cambia en tu cuenta de Microsoft.")
    if not verify_password(data.actual, user.password_hash):
        raise HTTPException(400, "La contraseña actual no es correcta")
    if data.nueva == data.actual:
        raise HTTPException(422, "La contraseña nueva debe ser distinta de la actual")
    user.password_hash = hash_password(data.nueva)
    era_temporal = user.debe_cambiar_password
    user.debe_cambiar_password, user.password_temporal_expira = False, None
    auditar(db, "password_cambiada", usuario_id=user.id, actor_id=user.id,
            detalle="cambio de contraseña temporal" if era_temporal else None, request=request)
    db.commit()
