"""Manuales de usuario que corresponden a cada persona (/manuales/ se abre sin iniciar sesión).

El índice de manuales usa esta lista para mostrar solo los de la persona que tiene la sesión abierta.
"""
from fastapi import APIRouter, Depends

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


@router.get("")
def mis_manuales(user: Usuario = Depends(get_current_user)):
    p = permitidos(user)
    return {"manuales": [f"manual-{k}.html" for k in p],
            "presentaciones": [f"presentaciones/{PRESENTACIONES[k]}" for k in p]}

