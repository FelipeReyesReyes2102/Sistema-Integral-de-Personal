"""Acceso a los manuales de usuario (/manuales/, servidos por el contenedor web).

Nginx pregunta aquí (auth_request) antes de entregar cada archivo: sin sesión responde 401 (va a iniciar sesión) y
si el manual no corresponde a la persona, 403. Las imágenes y el índice los ve cualquiera con sesión.
"""
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..models import ROL_ADMINISTRADOR, ROL_CASETA, ROL_SUPERADMIN, ROLES_SIN_VACACIONES, Usuario, es_admin, es_medico
from ..security import get_current_user

router = APIRouter(prefix="/api/manuales", tags=["manuales"])

MANUALES = ("empleado", "jefe", "gh", "caseta", "servicio-medico", "superadmin")
PRESENTACIONES = {
    "empleado": "SIP-O - Manual del empleado.pptx", "jefe": "SIP-O - Manual del jefe.pptx",
    "gh": "SIP-O - Manual de Gestión Humana.pptx", "caseta": "SIP-O - Manual de caseta.pptx",
    "servicio-medico": "SIP-O - Manual del servicio médico.pptx",
    "superadmin": "SIP-O - Manual del super administrador.pptx",
}


def permitidos(u: Usuario) -> list[str]:
    """Manuales según lo que usa cada persona."""
    if u.rol == ROL_SUPERADMIN:
        return list(MANUALES)
    p = []
    if u.rol not in ROLES_SIN_VACACIONES:
        p.append("empleado")
    if u.es_jefe or es_admin(u):
        p.append("jefe")
    if es_admin(u) or u.rol == ROL_ADMINISTRADOR:
        p.append("gh")
    if u.rol == ROL_CASETA:
        p.append("caseta")
    if es_medico(u):
        p.append("servicio-medico")
    return p


def manual_de_ruta(ruta: str) -> str | None:
    """Qué manual protege un archivo de /manuales/ ("" = libre con sesión; None = no se publica)."""
    r = unquote(ruta.split("?", 1)[0])
    if not r.startswith("/manuales"):
        return None
    r = r[len("/manuales"):].lstrip("/")
    if r in ("", "index.html") or (r.startswith("img/") and ".." not in r):
        return ""
    if r.startswith("manual-") and r.endswith(".html") and r[7:-5] in MANUALES:
        return r[7:-5]
    if r.startswith("presentaciones/"):
        return next((k for k, n in PRESENTACIONES.items() if r == f"presentaciones/{n}"), None)
    return None


@router.get("")
def mis_manuales(user: Usuario = Depends(get_current_user)):
    p = permitidos(user)
    return {"manuales": [f"manual-{k}.html" for k in p],
            "presentaciones": [f"presentaciones/{PRESENTACIONES[k]}" for k in p]}


@router.get("/acceso", include_in_schema=False)
def acceso(request: Request, user: Usuario = Depends(get_current_user)):
    manual = manual_de_ruta(request.headers.get("x-original-uri", ""))
    if manual is None or (manual and manual not in permitidos(user)):
        raise HTTPException(403, "Este manual no corresponde a tu tipo de usuario.")
    return Response(status_code=204)
