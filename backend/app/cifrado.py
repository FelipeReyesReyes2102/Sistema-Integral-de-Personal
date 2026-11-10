"""Cifrado de datos clínicos en la base de datos (Fernet, con una llave derivada de SECRET_KEY).

Los textos se guardan como "enc1:<token>". Los valores anteriores sin prefijo se leen tal cual y la migración
los cifra. Si SECRET_KEY cambia, los textos ya cifrados no se pueden leer: SECRET_KEY no debe cambiarse.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .config import settings

PREFIJO = "enc1:"
ILEGIBLE = "[No se pudo descifrar]"
log = logging.getLogger("sip.cifrado")


def _fernet() -> Fernet:
    llave = base64.urlsafe_b64encode(hashlib.sha256(f"sip-clinico:{settings.secret_key}".encode()).digest())
    return Fernet(llave)


def cifrar(texto: str | None) -> str | None:
    if texto is None or texto.startswith(PREFIJO):
        return texto
    return PREFIJO + _fernet().encrypt(texto.encode()).decode()


def descifrar(texto: str | None) -> str | None:
    if texto is None or not texto.startswith(PREFIJO):
        return texto
    try:
        return _fernet().decrypt(texto[len(PREFIJO):].encode()).decode()
    except InvalidToken:
        log.error("No se pudo descifrar un dato clínico (¿cambió SECRET_KEY?)")
        return ILEGIBLE


class TextoCifrado(TypeDecorator):
    """Columna de texto que se cifra al guardar y se descifra al leer."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return cifrar(value)

    def process_result_value(self, value, dialect):
        return descifrar(value)
