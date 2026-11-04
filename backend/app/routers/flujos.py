"""Cadenas de aprobación de la sede activa (GH): se arman aquí y se asignan a cada tipo de permiso."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import flujos as fl
from ..database import get_db
from ..models import FlujoAprobacion, FlujoPaso, TipoPermisoSede, Usuario
from ..schemas import FlujoIn, FlujoOut, FlujoPasoOut
from ..security import ahora, require_admin
from ..sedes import Alcance, alcance

router = APIRouter(prefix="/api/flujos", tags=["flujos de aprobación"])


def _out(db: Session, f: FlujoAprobacion) -> FlujoOut:
    tipos = db.scalars(select(TipoPermisoSede.nombre).where(TipoPermisoSede.flujo_id == f.id)
                       .order_by(TipoPermisoSede.orden, TipoPermisoSede.nombre)).all()
    pasos = [FlujoPasoOut(aprobador=p.aprobador, usuario_id=p.usuario_id, teams=p.teams, si_falta=p.si_falta,
                          etiqueta=fl.etiqueta(p.aprobador, p.usuario)) for p in f.pasos]
    return FlujoOut(id=f.id, nombre=f.nombre, activo=f.activo, pasos=pasos, tipos=list(tipos),
                    resumen=" → ".join(p.etiqueta for p in pasos))


def _del_alcance(db: Session, fid: int, alc: Alcance) -> FlujoAprobacion:
    f = db.get(FlujoAprobacion, fid)
    if not f or not alc.permite(f.sede_id):
        raise HTTPException(404, "Flujo de aprobación no encontrado")
    return f


def _aplicar(db: Session, f: FlujoAprobacion, data: FlujoIn, sede_id: int):
    nombre = data.nombre.strip()
    otro = db.scalar(select(FlujoAprobacion.id).where(FlujoAprobacion.sede_id == sede_id,
                                                      FlujoAprobacion.nombre == nombre, FlujoAprobacion.id != f.id))
    if otro:
        raise HTTPException(409, "Ya existe un flujo con ese nombre en la sede.")
    for i, p in enumerate(data.pasos, 1):
        if p.aprobador == "usuario":
            u = db.get(Usuario, p.usuario_id) if p.usuario_id else None
            if u is None or not u.activo or u.sede_id != sede_id:
                raise HTTPException(422, f"Paso {i}: elige una persona activa de la sede.")
    f.nombre, f.activo, f.actualizado = nombre, data.activo, ahora()
    f.pasos.clear()
    db.flush()
    for i, p in enumerate(data.pasos, 1):
        f.pasos.append(FlujoPaso(orden=i, aprobador=p.aprobador, teams=p.teams, si_falta=p.si_falta,
                                 usuario_id=p.usuario_id if p.aprobador == "usuario" else None))


@router.get("", response_model=list[FlujoOut])
def listar(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    lista = db.scalars(select(FlujoAprobacion).where(FlujoAprobacion.sede_id == alc.defecto)
                       .order_by(FlujoAprobacion.nombre)).all()
    return [_out(db, f) for f in lista]


@router.get("/aprobadores")
def aprobadores(_=Depends(require_admin)):
    """Tipos de aprobador que se pueden usar en un paso."""
    return [{"clave": k, "nombre": v} for k, v in fl.APROBADORES.items()]


@router.post("", response_model=FlujoOut, status_code=201)
def crear(data: FlujoIn, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    f = FlujoAprobacion(sede_id=alc.defecto)
    db.add(f)
    _aplicar(db, f, data, alc.defecto)
    db.commit()
    return _out(db, f)


@router.put("/{fid}", response_model=FlujoOut)
def editar(fid: int, data: FlujoIn, db: Session = Depends(get_db), _=Depends(require_admin),
           alc: Alcance = Depends(alcance)):
    f = _del_alcance(db, fid, alc)
    _aplicar(db, f, data, f.sede_id)
    db.commit()
    return _out(db, f)


@router.delete("/{fid}", status_code=204)
def borrar(fid: int, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    f = _del_alcance(db, fid, alc)
    usados = _out(db, f).tipos
    if usados:
        raise HTTPException(400, f"El flujo lo usan estos tipos de permiso: {', '.join(usados)}. Cámbialos primero.")
    db.delete(f)
    db.commit()
