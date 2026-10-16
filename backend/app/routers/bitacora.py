"""Consulta de la bitácora de cambios (GH, Gerencia GH y super administrador, según sus sedes)."""
import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bitacora
from ..security import require_admin
from ..sedes import Alcance, alcance

router = APIRouter(prefix="/api/bitacora", tags=["bitacora"])


@router.get("")
def listar(seccion: str, desde: date | None = None, hasta: date | None = None, q: str | None = None,
           accion: str | None = None, entidad: str | None = None, antes_de: int | None = None, limite: int = 50,
           db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    if seccion not in ("configuracion", "vacaciones"):
        raise HTTPException(422, "Apartado no válido")
    limite = max(1, min(limite, 200))
    cond = [Bitacora.seccion == seccion, alc.filtro(Bitacora.sede_id)]
    if desde:
        cond.append(Bitacora.fecha >= datetime.combine(desde, datetime.min.time()) - timedelta(hours=14))
    if hasta:
        cond.append(Bitacora.fecha < datetime.combine(hasta + timedelta(days=1), datetime.min.time()) + timedelta(hours=14))
    if accion:
        cond.append(Bitacora.accion == accion)
    if entidad:
        cond.append(Bitacora.entidad == entidad)
    if q and q.strip():
        t = f"%{q.strip()}%"
        cond.append(or_(Bitacora.descripcion.ilike(t), Bitacora.actor_nombre.ilike(t), Bitacora.cambios.ilike(t),
                        Bitacora.entidad.ilike(t)))
    if antes_de:
        cond.append(Bitacora.id < antes_de)
    filas = db.scalars(select(Bitacora).where(*cond).order_by(Bitacora.id.desc()).limit(limite + 1)).all()
    entidades = sorted(set(db.scalars(select(Bitacora.entidad).where(Bitacora.seccion == seccion, alc.filtro(Bitacora.sede_id))
                                      .distinct())))
    return {
        "items": [{
            "id": b.id, "fecha": b.fecha, "accion": b.accion, "entidad": b.entidad, "entidad_id": b.entidad_id,
            "descripcion": b.descripcion, "sede_nombre": b.sede_nombre, "actor_nombre": b.actor_nombre, "ip": b.ip,
            "cambios": json.loads(b.cambios or "[]"),
        } for b in filas[:limite]],
        "hay_mas": len(filas) > limite,
        "entidades": entidades,
    }
