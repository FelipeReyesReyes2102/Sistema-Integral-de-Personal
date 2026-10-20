"""Incapacidades: las ve el empleado, las valida su jefe (o GH) y GH las consulta todas."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import incapacidades as inc
from ..database import get_db
from ..models import SOLICITADO, Incapacidad, Usuario, es_admin
from ..schemas import IncapacidadOut, RechazoIn, ValidarIncapacidadIn
from ..security import get_current_user
from ..sedes import Alcance, alcance
from ..services import empleado_visible

router = APIRouter(prefix="/api/incapacidades", tags=["incapacidades"])


@router.get("", response_model=list[IncapacidadOut])
def listar(estado: str | None = None, por_aprobar: bool = False, todos: bool = False, usuario_id: int | None = None,
           db: Session = Depends(get_db), user: Usuario = Depends(get_current_user), alc: Alcance = Depends(alcance)):
    """- `todos` (GH): las de sus sedes. - `por_aprobar`: las que me toca validar. - Sin parámetros: las mías."""
    q = select(Incapacidad).order_by(Incapacidad.fecha_inicio.desc(), Incapacidad.id.desc())
    if todos and es_admin(user):
        q = q.where(Incapacidad.usuario_id.in_(select(Usuario.id).where(alc.filtro(Usuario.sede_id))))
    elif por_aprobar:
        q = q.where(Incapacidad.aprobador_id == user.id, Incapacidad.usuario_id != user.id)
    else:
        q = q.where(Incapacidad.usuario_id == empleado_visible(db, user, usuario_id).id)
    if estado:
        q = q.where(Incapacidad.estado == estado)
    return [inc.out(i) for i in db.scalars(q.limit(500))]


def _obtener(db: Session, iid: int, user: Usuario) -> Incapacidad:
    i = db.get(Incapacidad, iid)
    if not i or not inc.puede_ver(user, i):
        raise HTTPException(404, "Incapacidad no encontrada")
    return i


@router.get("/{iid}", response_model=IncapacidadOut)
def detalle(iid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return inc.out(_obtener(db, iid, user))


@router.post("/{iid}/validar", response_model=IncapacidadOut)
def validar(iid: int, tareas: BackgroundTasks, data: ValidarIncapacidadIn | None = None, db: Session = Depends(get_db),
            user: Usuario = Depends(get_current_user)):
    """Valida la incapacidad; opcionalmente con otras fechas (el jefe ajusta los días) y un comentario."""
    i = _obtener(db, iid, user)
    data = data or ValidarIncapacidadIn()
    inc.revisar(db, i, user, validar=True, fecha_inicio=data.fecha_inicio, fecha_fin=data.fecha_fin,
                comentario=data.comentario)
    db.commit()
    tareas.add_task(inc.notificar, i.id, "incapacidad_validada")
    return inc.out(i)


@router.post("/{iid}/rechazar", response_model=IncapacidadOut)
def rechazar(iid: int, data: RechazoIn, tareas: BackgroundTasks, db: Session = Depends(get_db),
             user: Usuario = Depends(get_current_user)):
    i = _obtener(db, iid, user)
    inc.revisar(db, i, user, validar=False, motivo=data.motivo)
    db.commit()
    tareas.add_task(inc.notificar, i.id, "incapacidad_rechazada")
    return inc.out(i)


@router.post("/{iid}/reenviar", response_model=IncapacidadOut)
def reenviar(iid: int, tareas: BackgroundTasks, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Vuelve a avisar al jefe de una incapacidad pendiente (médico o GH)."""
    i = _obtener(db, iid, user)
    if i.estado != SOLICITADO or not (es_admin(user) or i.medico_id == user.id):
        raise HTTPException(400, "Solo se reenvían incapacidades pendientes.")
    tareas.add_task(inc.notificar, i.id, "incapacidad_solicitada")
    return inc.out(i)
