"""Configuración editable desde la aplicación (tabla `configuracion`) con prioridad sobre `.env`.

- Solo se aplican las claves guardadas en la base; las demás conservan el valor de `.env`.
- Los secretos se cifran con Fernet usando una llave derivada de SECRET_KEY y nunca se devuelven.
- Cada proceso vuelve a leer la tabla como máximo cada 30 s (o al guardar), así funciona con varios workers.
"""
import base64
import hashlib
import logging
import threading
import time

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import ConfiguracionApp
from .security import ahora

log = logging.getLogger("sip.config")


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "si", "sí", "yes", "on")


# clave (variable de entorno) -> (atributo en settings, conversor, ¿secreto?)
CLAVES: dict[str, tuple[str, callable, bool]] = {
    "MICROSOFT_AUTH_ENABLED": ("microsoft_auth_enabled", _bool, False),
    "MICROSOFT_TENANT_ID": ("microsoft_tenant_id", str, False),
    "MICROSOFT_CLIENT_ID": ("microsoft_client_id", str, False),
    "MICROSOFT_CLIENT_SECRET": ("microsoft_client_secret", str, True),
    "MICROSOFT_REDIRECT_URI": ("microsoft_redirect_uri", str, False),
    "MICROSOFT_FRONTEND_URL": ("microsoft_frontend_url", str, False),
    "MICROSOFT_SCOPES": ("microsoft_scopes", str, False),
    "MICROSOFT_GRAPH_ENABLED": ("microsoft_graph_enabled", _bool, False),
    "PASSWORD_LOGIN_ENABLED": ("password_login_enabled", _bool, False),
    "PASSWORD_LOGIN_ROLES": ("password_login_roles", str, False),
}

# Valores de .env al arrancar, para restaurarlos si se borra la clave de la base
_BASE = {attr: getattr(settings, attr) for attr, _, _ in CLAVES.values()}
_aplicadas: set[str] = set()
_ultima = 0.0
_candado = threading.Lock()
INTERVALO = 30


def _fernet() -> Fernet:
    llave = base64.urlsafe_b64encode(hashlib.sha256(f"siv-config:{settings.secret_key}".encode()).digest())
    return Fernet(llave)


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def descifrar(texto: str) -> str | None:
    try:
        return _fernet().decrypt(texto.encode()).decode()
    except InvalidToken:
        log.warning("No se pudo descifrar un secreto guardado (¿cambió SECRET_KEY?). Captúralo de nuevo.")
        return None


def refrescar(db: Session, forzar: bool = False):
    """Aplica sobre `settings` los valores guardados en la base."""
    global _ultima
    if not forzar and time.monotonic() - _ultima < INTERVALO:
        return
    with _candado:
        filas = {f.clave: f for f in db.scalars(select(ConfiguracionApp))}
        for clave, (attr, conv, _secreto) in CLAVES.items():
            fila = filas.get(clave)
            if fila is None or fila.valor is None:
                if clave in _aplicadas:  # se borró: volver al valor de .env
                    setattr(settings, attr, _BASE[attr])
                    _aplicadas.discard(clave)
                continue
            valor = descifrar(fila.valor) if fila.cifrado else fila.valor
            if valor is None:
                continue
            setattr(settings, attr, conv(valor))
            _aplicadas.add(clave)
        _ultima = time.monotonic()


def guardar(db: Session, cambios: dict[str, str | None], actor_id: int | None):
    """Guarda (o borra con None) claves de configuración. Los secretos se cifran."""
    for clave, valor in cambios.items():
        if clave not in CLAVES:
            continue
        _attr, _conv, secreto = CLAVES[clave]
        fila = db.get(ConfiguracionApp, clave)
        if valor is None:
            if fila:
                db.delete(fila)
            continue
        if fila is None:
            fila = ConfiguracionApp(clave=clave)
            db.add(fila)
        fila.valor = cifrar(valor) if secreto else valor
        fila.cifrado = secreto
        fila.actualizado, fila.actualizado_por_id = ahora(), actor_id
    db.commit()
    refrescar(db, forzar=True)


def origenes(db: Session) -> dict[str, str]:
    """De dónde viene cada valor: 'configuracion' (base de datos) o 'env'."""
    guardadas = {f.clave for f in db.scalars(select(ConfiguracionApp)) if f.valor is not None}
    return {clave: ("configuracion" if clave in guardadas else "env") for clave in CLAVES}
