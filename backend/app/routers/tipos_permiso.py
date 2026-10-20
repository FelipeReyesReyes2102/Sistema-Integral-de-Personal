"""Tipos de permiso de la sede activa (GH de la sede); los empleados consultan los activos de su sede."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import tipos_permiso as tp
from ..database import get_db
from ..models import Permiso, Sede, TipoPermisoSede, Usuario
from ..schemas import TipoPermisoIn, TipoPermisoOut
from ..security import get_current_user, require_admin
from ..sedes import Alcance, alcance

router = APIRouter(prefix="/api", tags=["tipos de permiso"])


def _out(db: Session, t: TipoPermisoSede) -> TipoPermisoOut:
    o = TipoPermisoOut.model_validate(t)
    o.en_uso = db.scalar(select(func.count(Permiso.id)).join(Usuario, Usuario.id == Permiso.usuario_id)
                         .where(Permiso.tipo == t.clave, Usuario.sede_id == t.sede_id)) or 0
    return o


def _validar(data: TipoPermisoIn):
    if data.limite_unidad == "horas" and data.modalidad == "dias":
        raise HTTPException(422, "Los permisos por días se limitan en días, no en horas.")


def _del_alcance(db: Session, tid: int, alc: Alcance) -> TipoPermisoSede:
    t = db.get(TipoPermisoSede, tid)
    if not t or not alc.permite(t.sede_id):
        raise HTTPException(404, "Tipo de permiso no encontrado")
    return t


@router.get("/tipos-permiso", response_model=list[TipoPermisoOut])
def listar(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    lista = tp.de_sede(db, alc.defecto)
    db.commit()
    return [_out(db, t) for t in lista]


@router.post("/tipos-permiso", response_model=TipoPermisoOut, status_code=201)
def crear(data: TipoPermisoIn, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    _validar(data)
    sede = db.get(Sede, alc.defecto)
    if any(t.nombre.lower() == data.nombre.strip().lower() for t in tp.de_sede(db, sede.id)):
        raise HTTPException(409, "Ya existe un tipo de permiso con ese nombre en la sede.")
    t = TipoPermisoSede(sede_id=sede.id, clave=tp.nueva_clave(db, sede.id, data.nombre), base=False, orden=100,
                        **{**data.model_dump(), "nombre": data.nombre.strip()})
    db.add(t)
    tp.sincronizar_sede(db, sede)
    db.commit()
    return _out(db, t)


@router.put("/tipos-permiso/{tid}", response_model=TipoPermisoOut)
def editar(tid: int, data: TipoPermisoIn, db: Session = Depends(get_db), _=Depends(require_admin),
           alc: Alcance = Depends(alcance)):
    _validar(data)
    t = _del_alcance(db, tid, alc)
    valores = data.model_dump()
    if t.base:  # los tipos base conservan su nombre y su forma de pedirse
        valores.pop("nombre")
        valores.pop("modalidad")
    for k, v in valores.items():
        setattr(t, k, v.strip() if isinstance(v, str) and k == "nombre" else v)
    tp.sincronizar_sede(db, db.get(Sede, t.sede_id))
    db.commit()
    return _out(db, t)


@router.delete("/tipos-permiso/{tid}", status_code=204)
def borrar(tid: int, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    t = _del_alcance(db, tid, alc)
    if t.base:
        raise HTTPException(400, "Los tipos base no se eliminan; desactívalo si la sede no lo usa.")
    if _out(db, t).en_uso:
        raise HTTPException(400, "Ese tipo ya tiene permisos registrados; desactívalo para que no se pueda pedir.")
    sede = db.get(Sede, t.sede_id)
    db.delete(t)
    db.flush()
    tp.sincronizar_sede(db, sede)
    db.commit()

