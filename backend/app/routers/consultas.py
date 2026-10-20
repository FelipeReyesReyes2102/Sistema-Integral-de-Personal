"""Consultas del servicio médico de planta.

- El médico registra la consulta: paciente (filtrado por tipo de usuario), síntomas, diagnóstico,
  medicamentos recetados, indicaciones y resultado.
- El paciente ve sus consultas completas (en su calendario y lista).
- El administrador ve los registros completos (cada consulta abierta queda en la auditoría).
- El jefe solo ve que hubo consulta y su horario, nunca la información clínica.
"""
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import incapacidades
from ..database import get_db
from ..models import ROL_ADMIN, ROL_MEDICO, ROLES, ConsultaMedica, MedicamentoRecetado, Usuario
from ..models import ROLES_ADMIN, es_admin, es_medico  # noqa: F401
from ..schemas import ConsultaIn, ConsultaOut, ConsultaResumenOut, PacienteOut
from ..security import auditar, get_current_user, require_medico
from ..services import empleado_visible
from ..sedes import Alcance, admin_permite, alcance

router = APIRouter(prefix="/api/consultas", tags=["servicio médico"])


def _completo(c: ConsultaMedica) -> ConsultaOut:
    o = ConsultaOut.model_validate(c)
    o.paciente_nombre = c.paciente.nombre if c.paciente else None
    o.paciente_numero = c.paciente.numero_empleado if c.paciente else None
    o.paciente_rol = c.paciente.rol if c.paciente else None
    o.paciente_departamento = c.paciente.departamento if c.paciente else None
    o.medico_nombre = c.medico.nombre if c.medico else None
    o.incapacidad = incapacidades.out(c.incapacidad) if c.incapacidad else None
    return o


def _resumen(c: ConsultaMedica) -> ConsultaResumenOut:
    o = ConsultaResumenOut.model_validate(c)
    o.paciente_nombre = c.paciente.nombre if c.paciente else None
    o.medico_nombre = c.medico.nombre if c.medico else None
    o.incapacidad = incapacidades.out(c.incapacidad) if c.incapacidad else None
    return o


def _puede_ver_detalle(user: Usuario, c: ConsultaMedica) -> bool:
    if c.paciente_id == user.id:
        return True
    sede = c.paciente.sede_id if c.paciente else None
    return (es_medico(user) and user.sede_id == sede) or admin_permite(user, sede)


@router.get("/pacientes", response_model=list[PacienteOut])
def pacientes(rol: str | None = None, q: str | None = None, db: Session = Depends(get_db),
              medico: Usuario = Depends(require_medico)):
    """Empleados activos de la sede del médico, filtrados por tipo de usuario y búsqueda."""
    stmt = select(Usuario).where(Usuario.activo.is_(True), Usuario.sede_id == medico.sede_id).order_by(Usuario.nombre)
    if rol:
        if rol not in ROLES:
            raise HTTPException(400, "Tipo de usuario no válido")
        stmt = stmt.where(Usuario.rol == rol)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Usuario.nombre.ilike(like), Usuario.numero_empleado.ilike(like),
                              Usuario.departamento.ilike(like)))
    res = []
    for u in db.scalars(stmt.limit(200)):
        p = PacienteOut.model_validate(u)
        p.tiene_foto = u.foto_tipo is not None
        res.append(p)
    return res


@router.get("")
def listar(usuario_id: int | None = None, desde: date | None = None, hasta: date | None = None,
           rol: str | None = None, q: str | None = None, todos: bool = False,
           db: Session = Depends(get_db), user: Usuario = Depends(get_current_user), alc: Alcance = Depends(alcance)):
    """
    - Médico con `todos=true`: todas las consultas (filtros de fecha, tipo de usuario y búsqueda).
    - Sin parámetros: mis consultas (detalle completo).
    - `usuario_id`: consultas de un colaborador (jefe/administrador: solo resumen).
    """
    stmt = select(ConsultaMedica).order_by(ConsultaMedica.fecha.desc(), ConsultaMedica.hora_inicio.desc())
    if todos and (es_medico(user) or es_admin(user)):
        stmt = stmt.join(Usuario, Usuario.id == ConsultaMedica.paciente_id).where(alc.filtro(Usuario.sede_id))
        if rol or q:
            if rol:
                stmt = stmt.where(Usuario.rol == rol)
            if q:
                like = f"%{q.strip()}%"
                stmt = stmt.where(or_(Usuario.nombre.ilike(like), Usuario.numero_empleado.ilike(like)))
    elif (es_medico(user) or es_admin(user)) and usuario_id:
        paciente = db.get(Usuario, usuario_id)
        if not paciente or not (alc.permite(paciente.sede_id) or admin_permite(user, paciente.sede_id)):
            raise HTTPException(404, "Empleado no encontrado")
        stmt = stmt.where(ConsultaMedica.paciente_id == usuario_id)  # historial del paciente
    else:
        stmt = stmt.where(ConsultaMedica.paciente_id == empleado_visible(db, user, usuario_id).id)
    if desde:
        stmt = stmt.where(ConsultaMedica.fecha >= desde)
    if hasta:
        stmt = stmt.where(ConsultaMedica.fecha <= hasta)
    return [(_completo(c) if _puede_ver_detalle(user, c) else _resumen(c)).model_dump(mode="json")
            for c in db.scalars(stmt.limit(500))]


@router.get("/{cid}", response_model=ConsultaOut)
def detalle(cid: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    c = db.get(ConsultaMedica, cid)
    if not c or not _puede_ver_detalle(user, c):
        raise HTTPException(404, "Consulta no encontrada")
    if es_admin(user) and c.paciente_id != user.id:
        auditar(db, "consulta_vista_admin", usuario_id=c.paciente_id, actor_id=user.id, detalle=f"consulta {c.id}",
                request=request)
        db.commit()
    return _completo(c)


def _validar(db: Session, data: ConsultaIn, medico: Usuario) -> Usuario:
    paciente = db.get(Usuario, data.paciente_id)
    if not paciente or not paciente.activo:
        raise HTTPException(404, "El paciente no existe o está inactivo")
    if paciente.id == medico.id:
        raise HTTPException(422, "No puedes registrar una consulta a tu propio nombre")
    if paciente.sede_id != medico.sede_id:
        raise HTTPException(422, "El paciente pertenece a otra sede.")
    if medico.sede is not None and not medico.sede.modulo_consultas:
        raise HTTPException(403, "El servicio médico no está habilitado en tu sede.")
    if data.fecha > date.today():
        raise HTTPException(422, "La fecha de la consulta no puede ser futura")
    if data.hora_fin and data.hora_fin <= data.hora_inicio:
        raise HTTPException(422, "La hora de salida debe ser posterior a la de llegada")
    return paciente


def _aplicar(c: ConsultaMedica, data: ConsultaIn):
    c.paciente_id, c.fecha, c.hora_inicio, c.hora_fin = data.paciente_id, data.fecha, data.hora_inicio, data.hora_fin
    c.sintomas = data.sintomas.strip()
    c.diagnostico = (data.diagnostico or "").strip() or None
    c.indicaciones = (data.indicaciones or "").strip() or None
    c.resultado = data.resultado
    c.medicamentos = [MedicamentoRecetado(**m.model_dump()) for m in data.medicamentos if m.nombre.strip()]


@router.post("", response_model=ConsultaOut, status_code=201)
def crear(data: ConsultaIn, request: Request, tareas: BackgroundTasks, db: Session = Depends(get_db),
          medico: Usuario = Depends(require_medico)):
    paciente = _validar(db, data, medico)
    c = ConsultaMedica(medico_id=medico.id)
    _aplicar(c, data)
    avisar = incapacidades.aplicar(db, c, data.incapacidad, paciente, medico)
    db.add(c)
    db.flush()
    auditar(db, "consulta_registrada", usuario_id=data.paciente_id, actor_id=medico.id, detalle=f"consulta {c.id}",
            request=request)
    db.commit()
    if avisar:
        tareas.add_task(incapacidades.notificar, c.incapacidad.id, "incapacidad_solicitada")
    return _completo(c)


@router.put("/{cid}", response_model=ConsultaOut)
def editar(cid: int, data: ConsultaIn, request: Request, tareas: BackgroundTasks, db: Session = Depends(get_db),
           medico: Usuario = Depends(require_medico)):
    c = db.get(ConsultaMedica, cid)
    if not c or not _puede_ver_detalle(medico, c):
        raise HTTPException(404, "Consulta no encontrada")
    paciente = _validar(db, data, medico)
    _aplicar(c, data)
    avisar = incapacidades.aplicar(db, c, data.incapacidad, paciente, medico)
    auditar(db, "consulta_editada", usuario_id=c.paciente_id, actor_id=medico.id, detalle=f"consulta {c.id}",
            request=request)
    db.commit()
    if avisar:
        tareas.add_task(incapacidades.notificar, c.incapacidad.id, "incapacidad_solicitada")
    return _completo(c)


@router.delete("/{cid}", status_code=204)
def eliminar(cid: int, request: Request, db: Session = Depends(get_db), medico: Usuario = Depends(require_medico)):
    c = db.get(ConsultaMedica, cid)
    if not c or not _puede_ver_detalle(medico, c):
        raise HTTPException(404, "Consulta no encontrada")
    if c.incapacidad is not None and c.incapacidad.estado != "solicitado":
        raise HTTPException(400, "La consulta tiene una incapacidad ya revisada por el jefe; no se puede eliminar.")
    auditar(db, "consulta_eliminada", usuario_id=c.paciente_id, actor_id=medico.id, detalle=f"consulta {c.id}",
            request=request)
    db.delete(c)
    db.commit()


@router.get("/resumen/hoy")
def resumen_hoy(db: Session = Depends(get_db), _=Depends(require_medico)):
    hoy = date.today()
    total = db.scalar(select(func.count(ConsultaMedica.id)).where(ConsultaMedica.fecha == hoy)) or 0
    a_casa = db.scalar(select(func.count(ConsultaMedica.id)).where(
        ConsultaMedica.fecha == hoy, ConsultaMedica.resultado == "envia_casa")) or 0
    return {"consultas_hoy": total, "enviados_a_casa_hoy": a_casa}
