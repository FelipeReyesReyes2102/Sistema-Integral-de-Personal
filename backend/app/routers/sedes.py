"""Sedes: consulta (todos ven las suyas) y administración (solo super administrador)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import microsoft
from ..config import settings
from ..database import get_db
from ..models import Sede, Usuario
from ..schemas import SedeIn, SedeOut
from ..security import auditar, get_current_user, require_superadmin
from ..sedes import crear_jornadas_base, sede_por_ubicacion, sedes_visibles, zona

router = APIRouter(prefix="/api/sedes", tags=["sedes"])


def _out(db: Session, s: Sede) -> SedeOut:
    o = SedeOut.model_validate(s)
    o.empleados = db.scalar(select(func.count(Usuario.id)).where(Usuario.sede_id == s.id, Usuario.activo.is_(True))) or 0
    return o


def _validar(data: SedeIn) -> SedeIn:
    data.nombre = data.nombre.strip()
    data.ubicacion_microsoft = (data.ubicacion_microsoft or "").strip() or None
    if zona(data.zona_horaria).key != data.zona_horaria:
        raise HTTPException(422, f"La zona horaria {data.zona_horaria} no es válida (p. ej. America/Mexico_City, America/Bogota).")
    return data


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe una sede con ese nombre o ubicación de Microsoft.")


@router.get("", response_model=list[SedeOut])
def listar(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return [_out(db, s) for s in sedes_visibles(db, user)]


@router.post("", response_model=SedeOut, status_code=201)
def crear(data: SedeIn, request: Request, db: Session = Depends(get_db), su: Usuario = Depends(require_superadmin)):
    s = Sede(**_validar(data).model_dump())
    db.add(s)
    _commit(db)
    crear_jornadas_base(db, s)
    auditar(db, "sede_creada", actor_id=su.id, detalle=s.nombre, request=request)
    db.commit()
    return _out(db, s)


@router.put("/{sede_id}", response_model=SedeOut)
def editar(sede_id: int, data: SedeIn, request: Request, db: Session = Depends(get_db),
           su: Usuario = Depends(require_superadmin)):
    s = db.get(Sede, sede_id)
    if not s:
        raise HTTPException(404, "Sede no encontrada")
    data = _validar(data)
    if not data.activa and s.activa:
        activos = db.scalar(select(func.count(Usuario.id)).where(Usuario.sede_id == s.id, Usuario.activo.is_(True))) or 0
        if activos:
            raise HTTPException(400, f"La sede tiene {activos} empleado(s) activo(s); cámbialos de sede antes de desactivarla.")
    for k, v in data.model_dump().items():
        setattr(s, k, v)
    _commit(db)
    auditar(db, "sede_editada", actor_id=su.id, detalle=s.nombre, request=request)
    db.commit()
    return _out(db, s)


@router.post("/importar-microsoft")
def importar_microsoft(request: Request, db: Session = Depends(get_db), su: Usuario = Depends(require_superadmin)):
    """Crea una sede por cada "Ubicación del trabajo" del directorio de Microsoft que aún no exista."""
    if not settings.graph_configurado:
        raise HTTPException(400, "La consulta a Microsoft no está configurada.")
    try:
        ubicaciones = microsoft.ubicaciones_trabajo()
    except microsoft.ErrorMicrosoft as e:
        raise HTTPException(e.status, e.mensaje)
    creadas = []
    for ubic in sorted(ubicaciones):
        if sede_por_ubicacion(db, ubic) is None:
            nueva = Sede(nombre=ubic[:120], ubicacion_microsoft=ubic[:200])
            db.add(nueva)
            _commit(db)
            crear_jornadas_base(db, nueva)
            creadas.append(ubic)
    if creadas:
        auditar(db, "sedes_importadas", actor_id=su.id, detalle=", ".join(creadas)[:500], request=request)
        db.commit()
    return {"ubicaciones": ubicaciones, "creadas": creadas}
