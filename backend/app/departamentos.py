"""Catálogo fijo de departamentos de O-tek."""
import unicodedata

DEPARTAMENTOS = [
    "AMP", "APT", "Comercial", "Compras", "Finanzas", "Gerencia", "GH", "Ingeniería",
    "Logística", "Producción", "Proyectos", "SGC", "Sistemas",
]

# Nombres anteriores (o de Microsoft) y el departamento que les corresponde
EQUIVALENCIAS = {
    "cadena de suministro": "Logística", "cadena de suministros": "Logística", "cadena suministro": "Logística",
    "operaciones": "Producción",
    "it": "Sistemas", "ti": "Sistemas",
    "gestion humana": "GH", "recursos humanos": "GH", "rh": "GH",
    "contabilidad": "Finanzas",
}


def _clave(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.lower().split())


_POR_CLAVE = {_clave(d): d for d in DEPARTAMENTOS} | EQUIVALENCIAS


def normalizar(texto: str | None) -> str | None:
    """Departamento del catálogo que corresponde al texto (sin importar mayúsculas ni acentos), o None."""
    if not texto or not texto.strip():
        return None
    return _POR_CLAVE.get(_clave(texto))
