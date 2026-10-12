"""Sección del jefe: lista de jefes aprobadores y personal a cargo con sus saldos."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ROL_ADMIN, SOLICITADO, VALIDADO, Permiso, SolicitudVacaciones, Usuario
from ..models import ROLES_ADMIN, es_admin  # noqa: F401
from ..schemas import JefeOut, MiembroEquipoOut
from ..security import get_current_user
from ..services import saldo_periodo, sincronizar_periodos, usuario_out

router = APIRouter(prefix="/api", tags=["jefes y equipo"])


@router.get("/jefes", response_model=list[JefeOut])
def jefes(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Usuarios que pueden aprobar solicitudes (jefes y administradores)."""
    q = (select(Usuario)
         .where(Usuario.activo.is_(True), or_(Usuario.es_jefe.is_(True), Usuario.rol.in_(ROLES_ADMIN)))
         .order_by(Usuario.nombre))
    return db.scalars(q).all()


@router.get("/departamentos", response_model=list[str])
def departamentos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Departamentos capturados en los empleados (para el formulario de permisos)."""
    q = select(Usuario.departamento).where(Usuario.departamento.is_not(None), Usuario.departamento != "").distinct()
    return sorted(db.scalars(q).all())


@router.get("/equipo", response_model=list[MiembroEquipoOut])
def mi_equipo(jefe_id: int | None = None, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Personal a cargo del usuario (o de `jefe_id` si es administrador) con su saldo de vacaciones."""
    jefe = user.id if not (jefe_id and es_admin(user)) else jefe_id
    hoy = date.today()
    res = []
    for u in db.scalars(select(Usuario).where(Usuario.jefe_id == jefe, Usuario.activo.is_(True)).order_by(Usuario.nombre)):
        saldos = [saldo_periodo(db, p) for p in sincronizar_periodos(db, u)]
        vigentes = [s for s in saldos if s.vigente]
        actual = vigentes[-1] if vigentes else (saldos[-1] if saldos else None)
        pendientes = (
            (db.scalar(select(func.count(SolicitudVacaciones.id)).where(
                SolicitudVacaciones.usuario_id == u.id, SolicitudVacaciones.estado == SOLICITADO)) or 0)
            + (db.scalar(select(func.count(Permiso.id)).where(
                Permiso.usuario_id == u.id, Permiso.estado == SOLICITADO)) or 0)
        )
        activas = select(SolicitudVacaciones).where(
            SolicitudVacaciones.usuario_id == u.id, SolicitudVacaciones.estado == VALIDADO,
            SolicitudVacaciones.fecha_fin >= hoy).order_by(SolicitudVacaciones.fecha_inicio)
        proxima = db.scalars(activas.limit(1)).first()
        m = MiembroEquipoOut(usuario=usuario_out(u), pendientes_por_aprobar=pendientes,
                             dias_restantes_vigentes=round(sum(s.dias_disponible for s in vigentes), 2),
                             dias_perdidos=round(sum(s.dias_perdidos for s in saldos), 2))
        # Periodo anterior al actual que todavía tiene saldo: se perderá al cumplir 18 meses
        anteriores = [s for s in vigentes[:-1] if s.dias_disponible > 0]
        if anteriores:
            m.dias_por_vencer, m.fecha_por_vencer = anteriores[0].dias_disponible, anteriores[0].fecha_vencimiento
        if actual:
            m.periodo_actual, m.vence = actual.nombre, actual.fecha_vencimiento
            m.dias_total, m.dias_tomados = actual.dias_total, actual.dias_validado
            m.dias_solicitados = round(actual.dias_solicitado + actual.dias_borrador, 2)
            m.dias_restantes = actual.dias_disponible
        if proxima:
            m.proximas_vacaciones = proxima.fecha_inicio
            m.de_vacaciones_hoy = proxima.fecha_inicio <= hoy
        res.append(m)
    return res
