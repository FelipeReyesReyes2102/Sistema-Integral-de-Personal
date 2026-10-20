"""Permisos de llegada tarde, salida temprana, salida durante la jornada y home office."""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from .. import correo, horarios, reglas
from ..database import get_db
from ..models import (
    BORRADOR, CANCELADO, ESTADOS_ACTIVOS, PERMISO_CONSULTA_MEDICA, PERMISO_HOME_OFFICE, RECHAZADO, ROL_ADMIN,
    SOLICITADO, VALIDADO, Permiso, SolicitudVacaciones, Usuario,
)
from ..models import ROLES_ADMIN, es_admin  # noqa: F401
from ..schemas import PermisoIn, PermisoOut, RechazoIn, ValidarPermisoIn
from ..security import get_current_user
from ..sedes import Alcance, admin_permite, alcance, hoy_de
from ..services import  aprobar,ciclo_de, empleado_visible, festivos_de, jornada_de, puede_revisar, resolver_aprobador

router = APIRouter(prefix="/api/permisos", tags=["permisos"])


def _out(p: Permiso) -> PermisoOut:
    o = PermisoOut.model_validate(p)
    o.usuario_nombre = p.usuario.nombre if p.usuario else None
    o.aprobador_nombre = p.aprobador.nombre if p.aprobador else None
    o.revisado_por_nombre = p.revisado_por.nombre if p.revisado_por else None
    o.tiene_firma = bool(p.firma)
    if p.tipo == PERMISO_HOME_OFFICE and p.usuario:
        db = object_session(p)
        fin = p.fecha_fin or p.fecha
        o.dias = len(reglas.dias_laborales(p.fecha, fin, ciclo_de(p.usuario), festivos_de(db, p.usuario, p.fecha, fin)))
    o.aprobado_jefe_nombre = p.aprobado_jefe.nombre if p.aprobado_jefe else None
    o.falta_gh = p.estado == SOLICITADO and p.aprobado_jefe_id is not None
    return o


def _validar_envio(motivo, tipo_nomina, firma, tipo=None):
    nomina = tipo_nomina if tipo != PERMISO_HOME_OFFICE else "n/a"  # home office no es ausencia
    faltan = [n for n, v in (("motivo", motivo), ("cómo se considera el tiempo en nómina", nomina),
                             ("firma", firma)) if not v]
    if faltan:
        raise HTTPException(422, f"Para enviar el permiso falta: {', '.join(faltan)}.")


def _home_office(db: Session, data: PermisoIn, empleado: Usuario, actor: Usuario, excluir_id: int | None) -> dict:
    """Home office: rango de días laborales; no descuenta horas ni vacaciones."""
    fin = data.fecha_fin or data.fecha
    if fin < data.fecha:
        raise HTTPException(422, "La fecha final del home office no puede ser anterior a la inicial.")
    maximo = empleado.sede.home_office_max_dias if empleado.sede else 31
    if (fin - data.fecha).days > maximo - 1:
        raise HTTPException(422, f"El home office puede solicitarse por máximo {maximo} días naturales a la vez.")
    if not es_admin(actor) and data.fecha < hoy_de(empleado):
        raise HTTPException(422, "No es posible solicitar home office en fechas pasadas.")
    dias = reglas.dias_laborales(data.fecha, fin, ciclo_de(empleado), festivos_de(db, empleado, data.fecha, fin))
    if not dias:
        raise HTTPException(422, "El rango no contiene días laborales.")
    choca_vac = db.scalar(select(SolicitudVacaciones.id).where(
        SolicitudVacaciones.usuario_id == empleado.id, SolicitudVacaciones.estado.in_(ESTADOS_ACTIVOS),
        SolicitudVacaciones.fecha_inicio <= fin, SolicitudVacaciones.fecha_fin >= data.fecha).limit(1))
    if choca_vac:
        raise HTTPException(422, "Ya tienes vacaciones en esas fechas.")
    q = select(Permiso.id).where(
        Permiso.usuario_id == empleado.id, Permiso.tipo == PERMISO_HOME_OFFICE, Permiso.estado.in_(ESTADOS_ACTIVOS),
        Permiso.fecha <= fin, func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= data.fecha)
    if excluir_id:
        q = q.where(Permiso.id != excluir_id)
    if db.scalar(q.limit(1)):
        raise HTTPException(422, "Ya tienes home office solicitado en alguno de esos días.")
    t = empleado.turno
    return {"horas": 0.0, "fecha_fin": fin,
            "hora_inicio": data.hora_inicio or (t.hora_entrada if t else time(8)),
            "hora_fin": data.hora_fin or (t.hora_salida if t else time(17))}


def _tipo_habilitado(empleado: Usuario, tipo: str):
    """Cada sede decide qué tipos de permiso usa."""
    habilitados = (empleado.sede.tipos_permiso or "").split(",") if empleado.sede else None
    if habilitados is not None and tipo != PERMISO_CONSULTA_MEDICA and tipo not in habilitados:
        raise HTTPException(422, "Ese tipo de permiso no está habilitado en tu sede.")


def _preparar(db: Session, data: PermisoIn, empleado: Usuario, actor: Usuario, excluir_id: int | None = None) -> dict:
    _tipo_habilitado(empleado, data.tipo)
    if data.tipo == PERMISO_HOME_OFFICE:
        return _home_office(db, data, empleado, actor, excluir_id)
    if not data.hora_inicio or not data.hora_fin:
        raise HTTPException(422, "Indica el horario del permiso.")
    return {"horas": _validar(data, empleado, actor), "fecha_fin": None,
            "hora_inicio": data.hora_inicio, "hora_fin": data.hora_fin}


def _validar(data: PermisoIn, empleado: Usuario, actor: Usuario) -> float:
    if data.tipo == PERMISO_CONSULTA_MEDICA:
        raise HTTPException(422, "Las consultas médicas ya no se solicitan: las registra el médico de planta.")
    horas = reglas.horas_permiso(data.hora_inicio, data.hora_fin)
    horario = horarios.horario_de(empleado.turno, data.fecha)
    jornada = max(horario["horas"], empleado.turno.horas_jornada) if horario else jornada_de(empleado).horas_dia
    if horas > jornada:
        raise HTTPException(422, f"El permiso ({horas:g} h) excede la jornada de {jornada} h.")
    if not es_admin(actor) and data.fecha < hoy_de(empleado) and data.tipo != PERMISO_CONSULTA_MEDICA:
        raise HTTPException(422, "No es posible registrar permisos en fechas pasadas.")
    return horas


@router.get("", response_model=list[PermisoOut])
def listar(estado: str | None = None, tipo: str | None = None, usuario_id: int | None = None, todos: bool = False,
           por_aprobar: bool = False, anio: int | None = None,
           db: Session = Depends(get_db), user: Usuario = Depends(get_current_user), alc: Alcance = Depends(alcance)):
    q = select(Permiso).order_by(Permiso.fecha.desc(), Permiso.hora_inicio.desc())
    if todos and es_admin(user):
        q = q.where(Permiso.usuario_id.in_(select(Usuario.id).where(alc.filtro(Usuario.sede_id))))
    elif por_aprobar:
        q = q.where(Permiso.aprobador_id == user.id, Permiso.usuario_id != user.id)
        if estado == SOLICITADO:  # las que ya aprobé y esperan a GH no son mías
            q = q.where(Permiso.aprobado_jefe_id.is_(None))
    else:
        q = q.where(Permiso.usuario_id == empleado_visible(db, user, usuario_id).id)
    if estado:
        q = q.where(Permiso.estado == estado)
    if tipo:
        q = q.where(Permiso.tipo == tipo)
    if anio:
        q = q.where(Permiso.fecha >= date(anio, 1, 1), Permiso.fecha <= date(anio, 12, 31))
    return [_out(p) for p in db.scalars(q)]


@router.post("", response_model=PermisoOut, status_code=201)
def crear(data: PermisoIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    empleado = user
    if data.usuario_id and data.usuario_id != user.id:
        if not es_admin(user):
            raise HTTPException(403, "No autorizado")
        empleado = db.get(Usuario, data.usuario_id) or _404()
        if not admin_permite(user, empleado.sede_id):
            _404()
    _tipo_habilitado(empleado, data.tipo)
    aprobador_id = resolver_aprobador(db, empleado, data.aprobador_id)
    v = _preparar(db, data, empleado, user)
    if data.enviar:
        _validar_envio(data.motivo, data.tipo_nomina, data.firma, data.tipo)
    p = Permiso(usuario_id=empleado.id, tipo=data.tipo, fecha=data.fecha, fecha_fin=v["fecha_fin"],
                hora_inicio=v["hora_inicio"], hora_fin=v["hora_fin"], horas=v["horas"], motivo=data.motivo,
                aprobador_id=aprobador_id,
                departamento=data.departamento or empleado.departamento, tipo_nomina=data.tipo_nomina,
                firma=data.firma, estado=SOLICITADO if data.enviar else BORRADOR)
    db.add(p)
    db.commit()
    return _out(p)


def _obtener(db: Session, pid: int, user: Usuario) -> Permiso:
    p = db.get(Permiso, pid)
    visible = p and (p.usuario_id == user.id or (es_admin(user) and admin_permite(user, p.usuario.sede_id))
                     or p.aprobador_id == user.id or p.usuario.jefe_id == user.id)
    if not visible:
        _404()
    return p


def _es_dueno_o_admin(p: Permiso, user: Usuario):
    if p.usuario_id != user.id and not es_admin(user):
        raise HTTPException(403, "Solo el solicitante puede modificar este permiso")


@router.put("/{pid}", response_model=PermisoOut)
def editar(pid: int, data: PermisoIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    p = _obtener(db, pid, user)
    _es_dueno_o_admin(p, user)
    if p.estado != BORRADOR:
        raise HTTPException(400, "Solo se pueden editar permisos en borrador")
    p.aprobador_id = resolver_aprobador(db, p.usuario, data.aprobador_id)
    v = _preparar(db, data, p.usuario, user, excluir_id=p.id)
    p.tipo, p.fecha, p.motivo = data.tipo, data.fecha, data.motivo
    p.fecha_fin, p.hora_inicio, p.hora_fin, p.horas = v["fecha_fin"], v["hora_inicio"], v["hora_fin"], v["horas"]
    p.departamento = data.departamento or p.departamento
    p.tipo_nomina = data.tipo_nomina
    if data.firma:
        p.firma = data.firma
    if data.enviar:
        _validar_envio(p.motivo, p.tipo_nomina, p.firma, p.tipo)
        p.estado = SOLICITADO
    db.commit()
    return _out(p)


@router.post("/{pid}/enviar", response_model=PermisoOut)
def enviar(pid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    p = _obtener(db, pid, user)
    _es_dueno_o_admin(p, user)
    if p.estado != BORRADOR:
        raise HTTPException(400, "El permiso ya fue enviado")
    _validar_envio(p.motivo, p.tipo_nomina, p.firma, p.tipo)
    p.aprobador_id = resolver_aprobador(db, p.usuario, p.aprobador_id)
    p.estado = SOLICITADO
    db.commit()
    return _out(p)


@router.get("/{pid}", response_model=PermisoOut)
def detalle(pid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return _out(_obtener(db, pid, user))


@router.get("/{pid}/firma")
def firma(pid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return {"firma": _obtener(db, pid, user).firma}


@router.post("/{pid}/cancelar", response_model=PermisoOut)
def cancelar(pid: int, tareas: BackgroundTasks, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    p = _obtener(db, pid, user)
    if p.usuario_id == user.id or es_admin(user):
        permitido = {BORRADOR, SOLICITADO} | ({VALIDADO} if es_admin(user) else set())
    elif puede_revisar(user, p):
        permitido = {VALIDADO}
    else:
        raise HTTPException(403, "No autorizado")
    if p.estado not in permitido:
        raise HTTPException(400, "Este permiso ya no se puede cancelar")
    estaba_autorizado = p.estado == VALIDADO
    p.estado = CANCELADO
    db.commit()
    if estaba_autorizado:  # caseta ya había sido avisada: avisar la cancelación
        tareas.add_task(correo.notificar_permiso, p.id, "permiso_cancelado")
    return _out(p)


@router.delete("/{pid}", status_code=204)
def eliminar(pid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    p = _obtener(db, pid, user)
    _es_dueno_o_admin(p, user)
    if p.estado != BORRADOR:
        raise HTTPException(400, "Solo se pueden eliminar borradores")
    db.delete(p)
    db.commit()


def _revisable(db: Session, pid: int, user: Usuario) -> Permiso:
    p = _obtener(db, pid, user)
    if not puede_revisar(user, p):
        raise HTTPException(403, "Solo el jefe asignado o el administrador puede aprobar este permiso")
    if p.estado != SOLICITADO:
        raise HTTPException(400, "Solo se pueden revisar permisos pendientes")
    return p


@router.post("/{pid}/validar", response_model=PermisoOut)
def validar(pid: int, tareas: BackgroundTasks, data: ValidarPermisoIn | None = None, db: Session = Depends(get_db),
            user: Usuario = Depends(get_current_user)):
    p = _revisable(db, pid, user)
    final = aprobar(p, user)
    if data and data.observaciones:
        p.observaciones = data.observaciones
    db.commit()
    # Aviso a caseta en segundo plano (solo al quedar validado): si el correo falla, la autorización no se afecta
    if final:
        tareas.add_task(correo.notificar_permiso, p.id, "permiso_autorizado")
    return _out(p)


@router.post("/{pid}/rechazar", response_model=PermisoOut)
def rechazar(pid: int, data: RechazoIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    p = _revisable(db, pid, user)
    p.estado, p.motivo_rechazo = RECHAZADO, data.motivo
    p.revisado_por_id, p.fecha_revision = user.id, datetime.now()
    db.commit()
    return _out(p)


def _404():
    raise HTTPException(404, "Permiso no encontrado")
