"""Configuración de la aprobación en Teams por flujo HTTP de Power Automate (sede activa)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import aprobacion_flujo as af
from ..database import get_db
from ..models import CanalAprobacion, Sede, SolicitudAprobacion, Usuario
from ..security import ahora, require_admin
from ..sedes import Alcance, alcance, sede_principal
from ..sharepoint import ErrorSharePoint

router = APIRouter(prefix="/api/aprobacion-flujo", tags=["aprobacion"])


class CanalIn(BaseModel):
    activo: bool
    tipos: list[str] = ["vacaciones", "permisos"]
    flujo_url: str | None = None  # solo si se cambia
    lista_url: str | None = None
    cuenta_flujo: str | None = None


def _sede(db: Session, alc: Alcance) -> Sede:
    sid = alc.defecto or sede_principal(db).id
    alc.exigir(sid)
    return db.get(Sede, sid)


def _estado(db: Session, sede: Sede) -> dict:
    c = db.scalar(select(CanalAprobacion).where(CanalAprobacion.sede_id == sede.id))
    cuentas = dict(db.execute(select(SolicitudAprobacion.estado, func.count()).where(SolicitudAprobacion.sede_id == sede.id)
                              .group_by(SolicitudAprobacion.estado)).all())
    recientes = db.scalars(select(SolicitudAprobacion).where(
        SolicitudAprobacion.sede_id == sede.id,
        (SolicitudAprobacion.error.is_not(None)) | (SolicitudAprobacion.decision_nota.is_not(None)))
        .order_by(SolicitudAprobacion.id.desc()).limit(10)).all()
    return {
        "sede_nombre": sede.nombre, "configurado": bool(c and c.flujo_url), "activo": bool(c and c.activo),
        "tipos": sorted(af.tipos_de(c)) if c else ["permisos", "vacaciones"],
        "lista_url": c.lista_url if c else None, "lista_nombre": c.lista_nombre if c else None,
        "cuenta_flujo": c.cuenta_flujo if c else None,
        "cuentas": {k: cuentas.get(k, 0) for k in ("pendiente", "enviada", "resuelta", "cerrada", "error")},
        "avisos": [{"folio": af.folio(s.tipo, s.registro_id), "estado": s.estado, "texto": s.decision_nota or s.error,
                    "fecha": s.actualizado} for s in recientes],
    }


@router.get("")
def obtener(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    return _estado(db, _sede(db, alc))


@router.put("")
def guardar(data: CanalIn, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
            alc: Alcance = Depends(alcance)):
    sede = _sede(db, alc)
    c = db.scalar(select(CanalAprobacion).where(CanalAprobacion.sede_id == sede.id))
    if not c:
        c = CanalAprobacion(sede_id=sede.id)
        db.add(c)
    if data.flujo_url:
        try:
            af.guardar_url(c, data.flujo_url)
        except ValueError as e:
            raise HTTPException(422, str(e))
    if data.lista_url and data.lista_url.strip() != (c.lista_url or ""):
        try:
            info = af.conectar_lista(data.lista_url)
        except ErrorSharePoint as e:
            raise HTTPException(422, e.mensaje)
        c.lista_url, c.sitio_id, c.lista_id, c.lista_nombre = data.lista_url.strip(), info["sitio_id"], info["lista_id"], info["lista_nombre"]
    tipos = [t for t in data.tipos if t in af.TIPOS]
    if data.activo and (not c.flujo_url or not c.lista_id or not tipos):
        raise HTTPException(422, "Para activar, pega la URL del flujo, conecta la lista de decisiones y elige al menos un tipo.")
    c.tipos, c.activo = ",".join(tipos), data.activo
    c.cuenta_flujo = (data.cuenta_flujo or "").strip().lower() or None
    c.actualizado, c.actualizado_por_id = ahora(), admin.id
    db.commit()
    return _estado(db, sede)


@router.post("/reintentar")
def reintentar(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    sede = _sede(db, alc)
    db.query(SolicitudAprobacion).filter(SolicitudAprobacion.sede_id == sede.id, SolicitudAprobacion.estado == "error") \
        .update({"estado": "pendiente", "intentos": 0})
    db.commit()
    af.enviar_pendientes()
    return _estado(db, sede)
