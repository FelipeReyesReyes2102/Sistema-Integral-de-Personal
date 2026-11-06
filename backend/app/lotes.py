"""Permisos de varios días pedidos juntos (lote): se aprueban o rechazan una sola vez.

`Permiso.lote` guarda el id del permiso principal (el primer día); el principal tiene `lote == id`. Solo el
principal genera el aviso por correo y la tarjeta de Teams (con todas las fechas); al decidirlo, en SIP-O o en Teams,
la misma decisión se aplica a los demás días del lote que estaban en el mismo punto de la aprobación.
"""
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from .models import CANCELADO, RECHAZADO, SOLICITADO, Permiso


def es_secundario(p) -> bool:
    """Día del lote que no es el principal: no genera correo ni tarjeta propia."""
    return isinstance(p, Permiso) and bool(p.lote) and p.lote != p.id


def miembros(db: Session, p: Permiso) -> list[Permiso]:
    if not p.lote:
        return [p]
    return list(db.scalars(select(Permiso).where(Permiso.lote == p.lote).order_by(Permiso.fecha)))


def fechas(db: Session, p: Permiso) -> list[date]:
    """Días del lote que siguen vigentes (sin cancelados ni rechazados aparte)."""
    return [m.fecha for m in miembros(db, p) if m.estado not in (CANCELADO,) and (m.estado != RECHAZADO or m.id == p.id)]


def texto_fechas(db: Session, p: Permiso) -> str | None:
    """«3 días: 10/11, 11/11 y 12/11» para el principal de un lote; None si es un permiso de un día."""
    if not p.lote:
        return None
    fs = fechas(db, p)
    if len(fs) < 2:
        return None
    partes = [f"{f:%d/%m}" for f in fs]
    return f"{len(fs)} días: {', '.join(partes[:-1])} y {partes[-1]}"


def punto(p: Permiso) -> tuple:
    """En qué punto de la aprobación está (estado, aprobación del jefe y paso actual de la cadena)."""
    from . import flujos
    paso = flujos.actual(p) if p.pasos else None
    return p.estado, p.aprobado_jefe_id, paso.orden if paso else None


def _hermanos(p: Permiso, antes: tuple) -> list[Permiso]:
    db = object_session(p)
    return [m for m in miembros(db, p) if m.id != p.id and m.estado == SOLICITADO and punto(m) == antes]


def aprobar(p: Permiso, antes: tuple, actor, canal: str = "sip", comentario: str | None = None,
            observaciones: str | None = None) -> list[int]:
    """Aplica la aprobación de `p` a los demás días del lote. Devuelve los ids que quedaron validados."""
    from .services import aprobar as aprobar_uno
    validados = []
    for m in _hermanos(p, antes):
        try:
            if aprobar_uno(m, actor, canal, comentario):
                validados.append(m.id)
        except HTTPException:
            continue  # ese día no le toca al actor (p. ej. cambió su cadena): queda pendiente
        if observaciones:
            m.observaciones = observaciones
        if p.tipo_nomina and not m.tipo_nomina:
            m.tipo_nomina = p.tipo_nomina
    return validados


def rechazar(p: Permiso, antes: tuple, actor, canal: str = "sip", comentario: str | None = None):
    """Aplica el rechazo de `p` (ya con su estado y motivo) a los demás días del lote."""
    from . import flujos
    for m in _hermanos(p, antes):
        flujos.rechazar(m, actor, canal, comentario)
        m.estado, m.motivo_rechazo, m.motivo_rechazo_pendiente = RECHAZADO, p.motivo_rechazo, p.motivo_rechazo_pendiente
        m.revisado_por_id, m.fecha_revision = actor.id, datetime.now()
