"""Salida de equipos de cómputo: solicitud del empleado, autorización del jefe, revisión de TI y registro en caseta."""
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import equipos as eq
from ..database import get_db
from ..models import (
    BORRADOR, CANCELADO, RECHAZADO, ROL_CASETA, SOLICITADO, VALIDADO, SalidaEquipo, Usuario, es_admin, es_ti,
)
from ..schemas import MotivoIn, RevisionTIIn, SalidaEquipoIn, SalidaEquipoOut
from ..security import ahora, auditar, get_current_user
from ..sedes import Alcance, admin_permite, alcance, hoy_de, normalizar, sedes_visibles
from ..services import resolver_aprobador

router = APIRouter(prefix="/api/equipos", tags=["salida de equipo"])


def _destino(db: Session, user: Usuario, usuario_id: int | None) -> Usuario:
    if usuario_id and usuario_id != user.id:
        if not es_admin(user):
            raise HTTPException(403, "Solo GH puede capturar solicitudes de otros empleados.")
        u = db.get(Usuario, usuario_id)
        if not u or not admin_permite(user, u.sede_id):
            raise HTTPException(404, "Empleado no encontrado")
        return u
    return user


def _validar(data: SalidaEquipoIn, empleado: Usuario, actor: Usuario):
    if data.fecha_fin < data.fecha_inicio:
        raise HTTPException(422, "La fecha de término no puede ser anterior a la de inicio.")
    if (data.fecha_fin - data.fecha_inicio).days > 366:
        raise HTTPException(422, "El plazo puede ser de máximo un año.")
    if not es_admin(actor) and data.fecha_inicio < hoy_de(empleado):
        raise HTTPException(422, "La fecha de inicio no puede ser pasada.")


def _aplicar(s: SalidaEquipo, data: SalidaEquipoIn):
    s.tipo_equipo, s.marca, s.modelo = data.tipo_equipo, data.marca.strip(), data.modelo.strip()
    s.serie = data.serie.strip()
    s.accesorios = (data.accesorios or "").strip() or None
    s.justificacion = data.justificacion.strip()
    s.fecha_inicio, s.fecha_fin = data.fecha_inicio, data.fecha_fin
    s.detalles = (data.detalles or "").strip() or None
    if data.firma:
        s.firma = data.firma


def _enviar(s: SalidaEquipo):
    if not s.firma:
        raise HTTPException(422, "Firma la solicitud para enviarla.")
    s.estado = SOLICITADO


@router.get("", response_model=list[SalidaEquipoOut])
def listar(estado: str | None = None, por_aprobar: bool = False, todos: bool = False, q: str | None = None,
           desde: date | None = None, hasta: date | None = None,
           db: Session = Depends(get_db), user: Usuario = Depends(get_current_user), alc: Alcance = Depends(alcance)):
    """- `todos` (solo TI): las de su sede. - `por_aprobar`: las que me toca autorizar como jefe. - Sin parámetros: las mías."""
    stmt = select(SalidaEquipo).order_by(SalidaEquipo.fecha_inicio.desc(), SalidaEquipo.id.desc())
    if todos and not es_ti(user):
        raise HTTPException(403, "Solo TI puede ver todas las salidas de equipo; como jefe ves las de tu equipo.")
    if todos:
        sedes = {s.id for s in sedes_visibles(db, user)} if es_admin(user) else {user.sede_id}
        if es_admin(user):
            sedes = {x for x in sedes if alc.permite(x)}
        stmt = stmt.where(SalidaEquipo.usuario_id.in_(select(Usuario.id).where(Usuario.sede_id.in_(sedes or {-1}))),
                          SalidaEquipo.estado != BORRADOR)
    elif por_aprobar:
        stmt = stmt.where(SalidaEquipo.aprobador_id == user.id, SalidaEquipo.usuario_id != user.id,
                          SalidaEquipo.estado != BORRADOR)
    else:
        stmt = stmt.where(SalidaEquipo.usuario_id == user.id)
    if estado == "revision_ti":  # autorizadas por el jefe que TI aún no revisa y no han salido
        stmt = stmt.where(SalidaEquipo.estado == VALIDADO, SalidaEquipo.ti_estado.is_(None),
                          SalidaEquipo.salida_registrada.is_(None))
    elif estado == "fuera":
        stmt = stmt.where(SalidaEquipo.salida_registrada.is_not(None), SalidaEquipo.regreso_registrado.is_(None))
    elif estado:
        stmt = stmt.where(SalidaEquipo.estado == estado)
    if desde:
        stmt = stmt.where(SalidaEquipo.fecha_fin >= desde)
    if hasta:
        stmt = stmt.where(SalidaEquipo.fecha_inicio <= hasta)
    res = [eq.out(s) for s in db.scalars(stmt.limit(500))]
    palabras = normalizar(q).split()
    if palabras:
        res = [o for o in res if all(w in normalizar(" ".join(x or "" for x in (
            o.usuario_nombre, o.usuario_numero, o.marca, o.modelo, o.serie, o.usuario_departamento))) for w in palabras)]
    return res


@router.get("/hoy")
def hoy(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Caseta (y TI / GH): salidas de equipo autorizadas del día y equipos que están fuera de planta."""
    if user.rol != ROL_CASETA and not es_ti(user):
        raise HTTPException(403, "No tienes acceso a este apartado.")
    sedes = {s.id for s in sedes_visibles(db, user)} | {user.sede_id} if es_admin(user) else {user.sede_id}
    dia = hoy_de(user)
    usuarios = select(Usuario.id).where(Usuario.sede_id.in_([x for x in sedes if x is not None] or [-1]))
    stmt = select(SalidaEquipo).where(SalidaEquipo.usuario_id.in_(usuarios), or_(
        (SalidaEquipo.estado == VALIDADO) & (SalidaEquipo.fecha_inicio <= dia) & (SalidaEquipo.fecha_fin >= dia),
        SalidaEquipo.salida_registrada.is_not(None) & SalidaEquipo.regreso_registrado.is_(None),
        (SalidaEquipo.estado == RECHAZADO) & (SalidaEquipo.ti_estado == "rechazado") & (SalidaEquipo.fecha_inicio <= dia)
        & (SalidaEquipo.fecha_fin >= dia)))
    filas = [eq.out(s) for s in db.scalars(stmt.order_by(SalidaEquipo.fecha_inicio))]
    return {"fecha": dia.isoformat(), "salidas": [f.model_dump(mode="json") for f in filas]}


@router.get("/{sid}", response_model=SalidaEquipoOut)
def detalle(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return eq.out(eq.obtener(db, sid, user))


@router.get("/{sid}/firmas")
def firmas(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Firmas del formato (solicitante y TI) para verlo o imprimirlo."""
    s = eq.obtener(db, sid, user)
    return {"solicitante": s.firma, "ti": s.ti_firma}


@router.post("", response_model=SalidaEquipoOut, status_code=201)
def crear(data: SalidaEquipoIn, request: Request, tareas: BackgroundTasks, db: Session = Depends(get_db),
          user: Usuario = Depends(get_current_user)):
    emp = _destino(db, user, data.usuario_id)
    _validar(data, emp, user)
    s = SalidaEquipo(usuario_id=emp.id, estado=BORRADOR, aprobador_id=resolver_aprobador(db, emp, data.aprobador_id))
    _aplicar(s, data)
    if data.enviar:
        _enviar(s)
    db.add(s)
    db.flush()
    auditar(db, "salida_equipo_registrada", usuario_id=emp.id, actor_id=user.id, detalle=f"salida {s.id} · SN {s.serie}",
            request=request)
    db.commit()
    if s.estado == SOLICITADO:
        tareas.add_task(eq.notificar, s.id, "equipo_solicitado")
    return eq.out(s)


@router.put("/{sid}", response_model=SalidaEquipoOut)
def editar(sid: int, data: SalidaEquipoIn, tareas: BackgroundTasks, db: Session = Depends(get_db),
           user: Usuario = Depends(get_current_user)):
    s = eq.obtener(db, sid, user)
    eq.exigir(s.usuario_id == user.id or admin_permite(user, s.usuario.sede_id), "Solo el solicitante puede modificarla.", 403)
    eq.exigir(s.estado == BORRADOR, "Solo se editan solicitudes en borrador.")
    _validar(data, s.usuario, user)
    s.aprobador_id = resolver_aprobador(db, s.usuario, data.aprobador_id)
    _aplicar(s, data)
    if data.enviar:
        _enviar(s)
    db.commit()
    if s.estado == SOLICITADO:
        tareas.add_task(eq.notificar, s.id, "equipo_solicitado")
    return eq.out(s)


@router.post("/{sid}/enviar", response_model=SalidaEquipoOut)
def enviar(sid: int, tareas: BackgroundTasks, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = eq.obtener(db, sid, user)
    eq.exigir(s.usuario_id == user.id or admin_permite(user, s.usuario.sede_id), "Solo el solicitante puede enviarla.", 403)
    eq.exigir(s.estado == BORRADOR, "La solicitud ya fue enviada.")
    _enviar(s)
    db.commit()
    tareas.add_task(eq.notificar, s.id, "equipo_solicitado")
    return eq.out(s)


@router.delete("/{sid}", status_code=204)
def eliminar(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = eq.obtener(db, sid, user)
    eq.exigir(s.usuario_id == user.id or admin_permite(user, s.usuario.sede_id), "Solo el solicitante puede eliminarla.", 403)
    eq.exigir(s.estado == BORRADOR, "Solo se eliminan borradores; una enviada se cancela.")
    db.delete(s)
    db.commit()


@router.post("/{sid}/cancelar", response_model=SalidaEquipoOut)
def cancelar(sid: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = eq.obtener(db, sid, user)
    eq.exigir(s.usuario_id == user.id or s.aprobador_id == user.id or admin_permite(user, s.usuario.sede_id),
              "No puedes cancelar esta solicitud.", 403)
    eq.exigir(s.estado in (SOLICITADO, VALIDADO) and s.salida_registrada is None,
              "Solo se cancelan solicitudes pendientes o autorizadas cuyo equipo no ha salido.")
    s.estado = CANCELADO
    auditar(db, "salida_equipo_cancelada", usuario_id=s.usuario_id, actor_id=user.id, detalle=f"salida {s.id}", request=request)
    db.commit()
    return eq.out(s)


# ---------------- Jefe ----------------
@router.post("/{sid}/validar", response_model=SalidaEquipoOut)
def validar(sid: int, tareas: BackgroundTasks, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = eq.obtener(db, sid, user)
    eq.exigir(eq.puede_revisar_jefe(user, s), "Solo el jefe asignado (o GH) puede autorizar esta salida.", 403)
    eq.exigir(s.estado == SOLICITADO, "Solo se autorizan solicitudes pendientes.")
    eq.autorizar_jefe(s, user)
    db.commit()
    tareas.add_task(eq.notificar, s.id, "equipo_autorizado")
    return eq.out(s)


@router.post("/{sid}/rechazar", response_model=SalidaEquipoOut)
def rechazar(sid: int, data: MotivoIn, tareas: BackgroundTasks, db: Session = Depends(get_db),
             user: Usuario = Depends(get_current_user)):
    s = eq.obtener(db, sid, user)
    eq.exigir(eq.puede_revisar_jefe(user, s), "Solo el jefe asignado (o GH) puede rechazar esta salida.", 403)
    eq.exigir(s.estado == SOLICITADO, "Solo se rechazan solicitudes pendientes.")
    eq.rechazar_jefe(s, user, data.motivo.strip())
    db.commit()
    tareas.add_task(eq.notificar, s.id, "equipo_rechazado")
    return eq.out(s)


# ---------------- TI ----------------
@router.post("/{sid}/ti/autorizar", response_model=SalidaEquipoOut)
def ti_autorizar(sid: int, data: RevisionTIIn, request: Request, db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user)):
    """Sello y firma de TI sobre una salida ya autorizada por el jefe."""
    s = eq.obtener(db, sid, user)
    eq.exigir(eq.puede_revisar_ti(user, s), "Solo TI de la sede puede revisar esta salida.", 403)
    eq.exigir(s.estado == VALIDADO and s.salida_registrada is None,
              "TI autoriza salidas ya autorizadas por el jefe y que aún no salen.")
    s.ti_estado, s.ti_por_id, s.ti_fecha = "autorizado", user.id, datetime.now()
    s.ti_nota = (data.nota or "").strip() or None
    if data.firma:
        s.ti_firma = data.firma
    auditar(db, "salida_equipo_ti_autorizada", usuario_id=s.usuario_id, actor_id=user.id, detalle=f"salida {s.id}",
            request=request)
    db.commit()
    return eq.out(s)


@router.post("/{sid}/ti/rechazar", response_model=SalidaEquipoOut)
def ti_rechazar(sid: int, data: MotivoIn, request: Request, tareas: BackgroundTasks, db: Session = Depends(get_db),
                user: Usuario = Depends(get_current_user)):
    """TI rechaza la salida (pendiente o ya autorizada por el jefe) antes de que el equipo salga: avisa al empleado y al jefe."""
    s = eq.obtener(db, sid, user)
    eq.exigir(eq.puede_revisar_ti(user, s), "Solo TI de la sede puede rechazar esta salida.", 403)
    eq.exigir(s.estado in (SOLICITADO, VALIDADO) and s.salida_registrada is None,
              "Solo se rechazan salidas pendientes o autorizadas cuyo equipo no ha salido.")
    motivo = data.motivo.strip()
    s.estado, s.motivo_rechazo = RECHAZADO, f"TI: {motivo}"
    s.ti_estado, s.ti_por_id, s.ti_fecha, s.ti_nota = "rechazado", user.id, datetime.now(), motivo
    auditar(db, "salida_equipo_ti_rechazada", usuario_id=s.usuario_id, actor_id=user.id,
            detalle=f"salida {s.id} · motivo: {motivo}", request=request)
    db.commit()
    tareas.add_task(eq.notificar, s.id, "equipo_rechazado_ti")
    return eq.out(s)


# ---------------- Caseta: revisión de seguridad ----------------
def _caseta(db: Session, sid: int, user: Usuario) -> SalidaEquipo:
    s = eq.obtener(db, sid, user)
    eq.exigir(user.rol == ROL_CASETA or admin_permite(user, s.usuario.sede_id), "Solo caseta registra la salida y el regreso.", 403)
    return s


@router.post("/{sid}/salida", response_model=SalidaEquipoOut)
def registrar_salida(sid: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _caseta(db, sid, user)
    eq.exigir(eq.puede_salir(s), "Esta salida no está autorizada para hoy (revisa el plazo, la autorización del jefe y la de TI).")
    s.salida_registrada, s.salida_por_id = datetime.now(), user.id
    auditar(db, "salida_equipo_salio", usuario_id=s.usuario_id, actor_id=user.id, detalle=f"salida {s.id} · SN {s.serie}",
            request=request)
    db.commit()
    return eq.out(s)


@router.post("/{sid}/regreso", response_model=SalidaEquipoOut)
def registrar_regreso(sid: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _caseta(db, sid, user)
    eq.exigir(s.salida_registrada is not None and s.regreso_registrado is None, "El equipo no está registrado como fuera de planta.")
    s.regreso_registrado, s.regreso_por_id = datetime.now(), user.id
    auditar(db, "salida_equipo_regreso", usuario_id=s.usuario_id, actor_id=user.id, detalle=f"salida {s.id} · SN {s.serie}",
            request=request)
    db.commit()
    return eq.out(s)


def pendientes(db: Session, user: Usuario) -> dict:
    """Para el círculo rojo: por autorizar como jefe y, para TI, autorizadas por el jefe sin revisar."""
    res = {"equipos": db.scalar(select(func.count(SalidaEquipo.id)).where(
        SalidaEquipo.aprobador_id == user.id, SalidaEquipo.usuario_id != user.id, SalidaEquipo.estado == SOLICITADO)) or 0}
    if es_ti(user):  # solo TI ve (y cuenta) todas las de su sede
        sedes_ti = {s.id for s in sedes_visibles(db, user)} if es_admin(user) else {user.sede_id}
        res["todas_equipos"] = db.scalar(select(func.count(SalidaEquipo.id)).where(
            SalidaEquipo.usuario_id.in_(select(Usuario.id).where(Usuario.sede_id.in_(sedes_ti or {-1}))),
            SalidaEquipo.estado == SOLICITADO)) or 0
        sedes = {s.id for s in sedes_visibles(db, user)} if es_admin(user) else {user.sede_id}
        res["ti_equipos"] = db.scalar(select(func.count(SalidaEquipo.id)).where(
            SalidaEquipo.usuario_id.in_(select(Usuario.id).where(Usuario.sede_id.in_(sedes or {-1}))),
            SalidaEquipo.estado == VALIDADO, SalidaEquipo.ti_estado.is_(None), SalidaEquipo.salida_registrada.is_(None),
            SalidaEquipo.fecha_fin >= hoy_de(user))) or 0
    return res
