"""Contraseñas, sesiones con cookie HttpOnly, protección CSRF y autorización por rol.

El navegador nunca recibe tokens de acceso: solo una cookie de sesión opaca (HttpOnly) y
una cookie CSRF legible por JavaScript que debe reenviarse en el encabezado `X-CSRF-Token`
en las peticiones que modifican datos (patrón *double submit* ligado a la sesión).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import ROL_ADMIN, ROL_MEDICO, Auditoria, Sesion, Usuario
from .models import ROL_SUPERADMIN, ROLES_ADMIN, es_admin  # noqa: F401

METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


def ahora() -> datetime:
    """UTC sin zona horaria (compatible con PostgreSQL y SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------- Contraseñas ----------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


HORAS_PASSWORD_TEMPORAL = 72
MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15
# Rutas permitidas mientras el usuario no cambie su contraseña temporal
RUTAS_CAMBIO_OBLIGATORIO = {"/api/auth/me", "/api/auth/cambiar-password", "/api/auth/logout", "/api/auth/config"}


def asignar_password_temporal(usuario: Usuario) -> str:
    """Genera una contraseña aleatoria de 6 dígitos que se debe cambiar al entrar. Devuelve el valor en claro
    (solo para mostrarlo una vez al administrador)."""
    temporal = f"{secrets.randbelow(1_000_000):06d}"
    usuario.password_hash = hash_password(temporal)
    usuario.debe_cambiar_password = True
    usuario.password_temporal_expira = ahora() + timedelta(hours=HORAS_PASSWORD_TEMPORAL)
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    return temporal


def password_inutilizable() -> str:
    """Hash imposible de adivinar para usuarios que solo entran con Microsoft."""
    return "!" + secrets.token_hex(32)


def verify_password(password: str, hashed: str) -> bool:
    if not hashed or hashed.startswith("!"):
        return False
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def puede_usar_password(usuario: Usuario) -> bool:
    roles = settings.roles_con_password
    return settings.password_login_enabled and (not roles or usuario.rol in roles)


# ---------------- Auditoría ----------------
def auditar(db: Session, evento: str, *, usuario_id: int | None = None, actor_id: int | None = None,
            detalle: str | None = None, request: Request | None = None):
    ip = request.client.host if request and request.client else None
    db.add(Auditoria(fecha=ahora(), usuario_id=usuario_id, actor_id=actor_id, evento=evento,
                     detalle=detalle[:2000] if detalle else None, ip=ip))


# ---------------- Sesiones ----------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def crear_sesion(db: Session, response: Response, usuario: Usuario, metodo: str, request: Request | None = None) -> Sesion:
    token = secrets.token_urlsafe(32)
    t = ahora()
    sesion = Sesion(
        id=_hash(token), usuario_id=usuario.id, metodo=metodo, csrf=secrets.token_urlsafe(24),
        creado=t, expira=t + timedelta(hours=settings.session_hours), ultimo_uso=t,
        ip=request.client.host if request and request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255] if request else None,
    )
    db.add(sesion)
    usuario.ultimo_acceso = t
    db.execute(delete(Sesion).where(Sesion.expira < t))  # limpieza oportunista
    db.commit()
    poner_cookies(response, token, sesion.csrf)
    return sesion


def _opciones_cookie() -> dict:
    return dict(max_age=settings.session_hours * 3600, secure=settings.session_cookie_secure,
                samesite=settings.session_cookie_samesite, path="/")


def poner_cookies(response: Response, token: str, csrf: str):
    response.set_cookie(settings.session_cookie_name, token, httponly=True, **_opciones_cookie())
    poner_cookie_csrf(response, csrf)


def poner_cookie_csrf(response: Response, csrf: str):
    """La cookie CSRF la lee el frontend para enviarla en la cabecera X-CSRF-Token (no es HttpOnly)."""
    response.set_cookie(settings.csrf_cookie_name, csrf, httponly=False, **_opciones_cookie())


def borrar_cookies(response: Response):
    for nombre in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(nombre, path="/", secure=settings.session_cookie_secure,
                               samesite=settings.session_cookie_samesite)


def sesion_actual(request: Request, db: Session) -> Sesion | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    sesion = db.get(Sesion, _hash(token))
    if not sesion or sesion.expira <= ahora():
        return None
    return sesion


def cerrar_sesion(request: Request, db: Session) -> Sesion | None:
    sesion = sesion_actual(request, db)
    if sesion:
        db.delete(sesion)
        db.commit()
    return sesion


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Usuario:
    sesion = sesion_actual(request, db)
    if not sesion:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tu sesión expiró o no has iniciado sesión")
    if request.method not in METODOS_SEGUROS:
        enviado = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(enviado, sesion.csrf):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Token CSRF inválido; recarga la página")
    user = sesion.usuario
    if not user or not user.activo:
        db.delete(sesion)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tu usuario está inactivo")
    if (user.debe_cambiar_password and sesion.metodo == "password"
            and request.url.path not in RUTAS_CAMBIO_OBLIGATORIO):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Debes cambiar tu contraseña temporal antes de continuar.")
    t = ahora()
    if (t - sesion.ultimo_uso).total_seconds() > 300:  # no escribir en cada petición
        sesion.ultimo_uso = t
        db.commit()
    request.state.sesion = sesion
    return user


# ---------------- Autorización por rol ----------------
def require_roles(*roles: str):
    """Dependencia: permite solo los roles indicados (tomados de la base de datos, no del navegador)."""
    def dependencia(user: Usuario = Depends(get_current_user)) -> Usuario:
        if user.rol not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para realizar esta acción")
        return user
    return dependencia


require_admin = require_roles(ROL_ADMIN, ROL_SUPERADMIN)
require_superadmin = require_roles(ROL_SUPERADMIN)
require_medico = require_roles(ROL_MEDICO)


def require_jefe(user: Usuario = Depends(get_current_user)) -> Usuario:
    if not (user.es_jefe or es_admin(user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los jefes pueden realizar esta acción")
    return user


def permisos_de(user: Usuario) -> list[str]:
    p = ["vacaciones:solicitar", "permisos:solicitar"]
    if user.es_jefe or es_admin(user):
        p += ["solicitudes:aprobar", "equipo:consultar"]
    if es_admin(user):
        p += ["usuarios:administrar", "catalogos:administrar", "solicitudes:todas"]
    if user.rol == ROL_SUPERADMIN:
        p += ["config:microsoft", "usuarios:superadmin"]
    if user.rol == ROL_MEDICO:
        p += ["consultas:registrar"]
    return p


def limpiar_sesiones_de(db: Session, usuario_id: int):
    """Cierra todas las sesiones de un usuario (p. ej. al desactivarlo)."""
    db.execute(delete(Sesion).where(Sesion.usuario_id == usuario_id))


def sesiones_activas(db: Session, usuario_id: int) -> int:
    return len(db.scalars(select(Sesion.id).where(Sesion.usuario_id == usuario_id, Sesion.expira > ahora())).all())
