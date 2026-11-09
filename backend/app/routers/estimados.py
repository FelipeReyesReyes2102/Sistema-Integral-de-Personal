"""Cumpleaños y aniversarios: los del personal de la sede se ven en el calendario de todos.

Cada quien decide si quiere verlos en su calendario (preferencias ver_cumpleanos / ver_aniversarios); los propios
siempre se ven. Del cumpleaños solo se muestra el día y el mes, nunca el año de nacimiento ni la edad.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Usuario
from ..security import get_current_user
from ..sedes import hoy_de

router = APIRouter(prefix="/api/estimados", tags=["cumpleaños y aniversarios"])
DIAS_PROXIMOS = 30


def _proximos(db: Session, user: Usuario) -> list[dict]:
    """Cumpleaños y aniversarios de la sede en los próximos días (según mis preferencias)."""
    from .calendario import _cumpleanos
    hoy = hoy_de(user)
    con = user.sede is None or user.sede.modulo_cumpleanos
    hasta = hoy + timedelta(days=DIAS_PROXIMOS)
    eventos = _cumpleanos(db, hoy.year, user, con) + (_cumpleanos(db, hasta.year, user, con) if hasta.year != hoy.year else [])
    return [e for e in eventos if hoy.isoformat() <= e["fecha"] <= hasta.isoformat()]


@router.get("")
def resumen(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return {"preferencias": {"ver_cumpleanos": user.ver_cumpleanos, "ver_aniversarios": user.ver_aniversarios},
            "proximos": _proximos(db, user), "dias": DIAS_PROXIMOS}


class PreferenciasIn(BaseModel):
    ver_cumpleanos: bool = True
    ver_aniversarios: bool = True


@router.put("/preferencias")
def preferencias(data: PreferenciasIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    user.ver_cumpleanos, user.ver_aniversarios = data.ver_cumpleanos, data.ver_aniversarios
    db.commit()
    return data
