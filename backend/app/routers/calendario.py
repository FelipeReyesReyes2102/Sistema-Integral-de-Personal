from calendar import monthrange
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import reglas
from ..database import get_db
from ..models import (
    ESTADOS_ACTIVOS, PERMISO_HOME_OFFICE, ROL_ADMIN, ROL_MEDICO, SOLICITADO, TIPOS_PERMISO, VALIDADO, ConsultaMedica, Festivo, Permiso,
    SolicitudVacaciones, Usuario,
)
from ..models import ROLES_ADMIN, es_admin  # noqa: F401
from ..security import get_current_user, require_admin
from ..services import ciclo_de, empleado_visible, festivos_de

router = APIRouter(prefix="/api", tags=["calendario y resumen"])


def _dias_vacaciones(db: Session, u: Usuario, desde: date, hasta: date) -> dict[str, dict]:
    """Días laborales cubiertos por solicitudes activas -> {fecha: {estado, id}}."""
    ciclo = ciclo_de(u)
    fest = festivos_de(db, u, desde - timedelta(days=60), hasta + timedelta(days=60))
    res: dict[str, dict] = {}
    q = select(SolicitudVacaciones).where(
        SolicitudVacaciones.usuario_id == u.id, SolicitudVacaciones.estado.in_(ESTADOS_ACTIVOS),
        SolicitudVacaciones.fecha_inicio <= hasta, SolicitudVacaciones.fecha_fin >= desde,
    )
    for s in db.scalars(q):
        for d in reglas.dias_laborales(max(s.fecha_inicio, desde), min(s.fecha_fin, hasta), ciclo, fest):
            res[d.isoformat()] = {"estado": s.estado, "id": s.id}
    return res


def _permisos_por_dia(db: Session, u: Usuario, desde: date, hasta: date) -> list[dict]:
    """Permisos activos; el home office se expande a cada día laboral de su rango."""
    ciclo = ciclo_de(u)
    fest = festivos_de(db, u, desde, hasta)
    res = []
    q = select(Permiso).where(
        Permiso.usuario_id == u.id, Permiso.estado.in_(ESTADOS_ACTIVOS),
        Permiso.fecha <= hasta, func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= desde)
    for p in db.scalars(q):
        base = {"tipo": p.tipo, "estado": p.estado, "id": p.id,
                "hora_inicio": p.hora_inicio.strftime("%H:%M"), "hora_fin": p.hora_fin.strftime("%H:%M")}
        if p.tipo == PERMISO_HOME_OFFICE:
            for d in reglas.dias_laborales(max(p.fecha, desde), min(p.fecha_fin or p.fecha, hasta), ciclo, fest):
                res.append({**base, "fecha": d.isoformat()})
        elif desde <= p.fecha <= hasta:
            res.append({**base, "fecha": p.fecha.isoformat()})
    return res


def _consultas(db: Session, u: Usuario, desde: date, hasta: date, con_detalle: bool) -> list[dict]:
    q = select(ConsultaMedica).where(ConsultaMedica.paciente_id == u.id, ConsultaMedica.fecha >= desde,
                                     ConsultaMedica.fecha <= hasta)
    return [{"fecha": c.fecha.isoformat(), "id": c.id if con_detalle else None,
             "hora_inicio": c.hora_inicio.strftime("%H:%M"),
             "hora_fin": c.hora_fin.strftime("%H:%M") if c.hora_fin else None} for c in db.scalars(q)]


@router.get("/calendario")
def calendario(anio: int, usuario_id: int | None = None, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    u = empleado_visible(db, user, usuario_id)
    desde, hasta = date(anio, 1, 1), date(anio, 12, 31)
    ciclo = ciclo_de(u)
    cat = reglas.categoria(u.rol)
    festivos = db.scalars(select(Festivo).where(Festivo.fecha >= desde, Festivo.fecha <= hasta,
                                                Festivo.aplica_a.in_(["todos", cat]))).all()
    no_laborables, d = [], desde
    while d <= hasta:
        if not ciclo.es_laboral(d):
            no_laborables.append(d.isoformat())
        d += timedelta(days=1)
    detalle_clinico = u.id == user.id or user.rol in (ROL_MEDICO, *ROLES_ADMIN)  # el jefe solo ve que hubo consulta
    return {
        "anio": anio,
        "festivos": [{"fecha": f.fecha.isoformat(), "nombre": f.nombre} for f in festivos],
        "no_laborables": no_laborables,
        "vacaciones": _dias_vacaciones(db, u, desde, hasta),
        "permisos": _permisos_por_dia(db, u, desde, hasta),
        "consultas": _consultas(db, u, desde, hasta, detalle_clinico),
    }


@router.get("/calendario/equipo")
def calendario_equipo(anio: int, mes: int, grupo_id: int | None = None, rol: str | None = None, q: str | None = None,
                      db: Session = Depends(get_db), _=Depends(require_admin)):
    """Vista mensual de todo el personal con todos sus eventos por día:
    vacaciones, permisos, home office y consultas médicas (más festivos y descansos)."""
    desde = date(anio, mes, 1)
    hasta = date(anio, mes, monthrange(anio, mes)[1])
    stmt = select(Usuario).where(Usuario.activo.is_(True)).order_by(Usuario.nombre)
    if grupo_id:
        stmt = stmt.where(Usuario.grupo_id == grupo_id)
    if rol:
        stmt = stmt.where(Usuario.rol == rol)
    if q:
        stmt = stmt.where(Usuario.nombre.ilike(f"%{q.strip()}%"))
    empleados = []
    totales = {"vacaciones": 0, "permiso": 0, "home_office": 0, "consulta": 0}
    for u in db.scalars(stmt):
        ciclo = ciclo_de(u)
        fest = {f.fecha: f.nombre for f in db.scalars(select(Festivo).where(
            Festivo.fecha >= desde, Festivo.fecha <= hasta, Festivo.aplica_a.in_(["todos", reglas.categoria(u.rol)])))}
        dias: dict[str, dict] = {}
        d = desde
        while d <= hasta:
            base = "festivo" if d in fest else ("descanso" if not ciclo.es_laboral(d) else None)
            dias[d.isoformat()] = {"base": base, "festivo": fest.get(d), "eventos": []}
            d += timedelta(days=1)
        for f, v in _dias_vacaciones(db, u, desde, hasta).items():
            dias[f]["eventos"].append({"cat": "vacaciones", "estado": v["estado"], "id": v["id"]})
            totales["vacaciones"] += 1
        for p in _permisos_por_dia(db, u, desde, hasta):
            cat = "home_office" if p["tipo"] == PERMISO_HOME_OFFICE else p["tipo"]
            dias[p["fecha"]]["eventos"].append({"cat": cat, "estado": p["estado"], "id": p["id"],
                                                 "hora_inicio": p["hora_inicio"], "hora_fin": p["hora_fin"]})
            totales["home_office" if cat == "home_office" else "permiso"] += 1
        for c in _consultas(db, u, desde, hasta, con_detalle=True):
            dias[c["fecha"]]["eventos"].append({"cat": "consulta", "estado": "registrada", "id": c["id"],
                                                 "hora_inicio": c["hora_inicio"], "hora_fin": c["hora_fin"]})
            totales["consulta"] += 1
        empleados.append({
            "id": u.id, "nombre": u.nombre, "rol": u.rol, "numero_empleado": u.numero_empleado,
            "tiene_foto": u.foto_tipo is not None, "puesto": u.puesto,
            "grupo": u.grupo.nombre if u.grupo else None, "grupo_color": u.grupo.color if u.grupo else None,
            "turno": u.turno.nombre if u.turno else None, "dias": dias,
        })
    return {"anio": anio, "mes": mes, "total_dias": hasta.day, "empleados": empleados, "totales": totales}


@router.get("/resumen/permisos")
def resumen_permisos(anio: int | None = None, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Horas solicitadas / validadas por tipo de permiso (tarjeta "Mis ausencias")."""
    anio = anio or date.today().year
    rows = db.execute(
        select(Permiso.tipo, Permiso.estado, func.coalesce(func.sum(Permiso.horas), 0), func.count(Permiso.id))
        .where(Permiso.usuario_id == user.id, Permiso.fecha >= date(anio, 1, 1), Permiso.fecha <= date(anio, 12, 31))
        .group_by(Permiso.tipo, Permiso.estado)
    ).all()
    por_tipo = {t: {"borrador": 0.0, "solicitado": 0.0, "validado": 0.0, "eventos": 0} for t in TIPOS_PERMISO}
    for tipo, estado, horas, n in rows:
        if tipo in por_tipo and estado in por_tipo[tipo]:
            por_tipo[tipo][estado] += float(horas)
            por_tipo[tipo]["eventos"] += n
    return {
        "anio": anio,
        "total_solicitado": sum(v["solicitado"] for v in por_tipo.values()),
        "total_validado": sum(v["validado"] for v in por_tipo.values()),
        "por_tipo": por_tipo,
    }


@router.get("/pendientes")
def pendientes(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Solicitudes por aprobar: las asignadas a mí como jefe y, si soy administrador, todas."""
    def contar(modelo, extra=()):
        q = select(func.count(modelo.id)).where(modelo.estado == SOLICITADO, *extra)
        return db.scalar(q) or 0

    mias = (SolicitudVacaciones.aprobador_id == user.id, SolicitudVacaciones.usuario_id != user.id)
    mias_p = (Permiso.aprobador_id == user.id, Permiso.usuario_id != user.id)
    res = {"vacaciones": contar(SolicitudVacaciones, mias), "permisos": contar(Permiso, mias_p)}
    res["total"] = res["vacaciones"] + res["permisos"]
    if es_admin(user):
        res["todas"] = contar(SolicitudVacaciones) + contar(Permiso)
    return res


@router.get("/admin/estadisticas")
def estadisticas(db: Session = Depends(get_db), _=Depends(require_admin)):
    hoy = date.today()
    por_rol = dict(db.execute(select(Usuario.rol, func.count(Usuario.id)).where(Usuario.activo.is_(True))
                              .group_by(Usuario.rol)).all())
    de_vacaciones = db.scalar(select(func.count(func.distinct(SolicitudVacaciones.usuario_id))).where(
        SolicitudVacaciones.estado == VALIDADO, SolicitudVacaciones.fecha_inicio <= hoy,
        SolicitudVacaciones.fecha_fin >= hoy)) or 0
    return {"empleados_por_rol": por_rol, "de_vacaciones_hoy": de_vacaciones}
