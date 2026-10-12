"""Servicios que combinan las reglas con la base de datos."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from . import reglas
from .config import settings
from .models import (
    BORRADOR, ESTADOS_ACTIVOS, ROL_ADMIN, SOLICITADO, VALIDADO, Festivo, Permiso, PeriodoVacaciones,
    ReglaAntiguedad, SolicitudVacaciones, Usuario,
)
from .models import ROLES_ADMIN, es_admin  # noqa: F401
from .schemas import PeriodoOut, UsuarioOut


def tabla_antiguedad(db: Session) -> list[tuple[int, int, int]]:
    rows = db.scalars(select(ReglaAntiguedad)).all()
    if not rows:
        return reglas.TABLA_ANTIGUEDAD_DEFAULT
    return [(r.anios_desde, r.anios_hasta, r.dias) for r in rows]


def ciclo_de(usuario: Usuario) -> reglas.Ciclo:
    """Oficinas: lunes a viernes. Planta: según el ciclo del grupo asignado."""
    g = usuario.grupo
    if reglas.categoria(usuario.rol) == "planta" and g is not None:
        return reglas.Ciclo(
            tipo=g.tipo_ciclo,
            dias_semana=reglas.parse_dias_semana(g.dias_semana),
            dias_trabajo=g.dias_trabajo,
            dias_descanso=g.dias_descanso,
            fecha_inicio=g.fecha_inicio_ciclo,
        )
    return reglas.Ciclo()


def festivos_de(db: Session, usuario: Usuario, desde: date, hasta: date) -> set[date]:
    cat = reglas.categoria(usuario.rol)
    rows = db.scalars(
        select(Festivo).where(Festivo.fecha >= desde, Festivo.fecha <= hasta,
                              Festivo.aplica_a.in_(["todos", cat]))
    ).all()
    return {f.fecha for f in rows}


def sincronizar_periodos(db: Session, usuario: Usuario, hoy: date | None = None) -> list[PeriodoVacaciones]:
    """Crea los periodos que falten y recalcula días/horas según la tabla y la categoría actual."""
    hoy = hoy or date.today()
    tabla = tabla_antiguedad(db)
    cat = reglas.categoria(usuario.rol)
    existentes = {p.numero: p for p in usuario.periodos}
    cambios = False
    for pc in reglas.periodos_hasta(usuario.fecha_ingreso, hoy, settings.vacaciones_al_cumplir_anio,
                                    settings.meses_vigencia_periodo):
        dias = reglas.dias_por_antiguedad(pc.numero, tabla)
        valores = dict(
            fecha_inicio=pc.fecha_inicio, fecha_vencimiento=pc.fecha_vencimiento, dias_ley=dias,
            horas_otorgadas=reglas.horas_otorgadas(dias), horas_por_dia=reglas.HORAS_DIA[cat],
        )
        p = existentes.get(pc.numero)
        if p is None:
            p = PeriodoVacaciones(usuario_id=usuario.id, numero=pc.numero, ajuste_horas=0, **valores)
            usuario.periodos.append(p)
            cambios = True
        else:
            for k, v in valores.items():
                if getattr(p, k) != v:
                    setattr(p, k, v)
                    cambios = True
    if cambios:
        db.commit()
    return sorted(usuario.periodos, key=lambda p: p.numero)


def horas_por_estado(db: Session, periodo_id: int, excluir_id: int | None = None) -> dict[str, float]:
    q = select(SolicitudVacaciones).where(
        SolicitudVacaciones.periodo_id == periodo_id, SolicitudVacaciones.estado.in_(ESTADOS_ACTIVOS)
    )
    res = {BORRADOR: 0.0, SOLICITADO: 0.0, VALIDADO: 0.0}
    for s in db.scalars(q):
        if s.id != excluir_id:
            res[s.estado] += s.horas
    return res


def tiene_bloque_minimo(db: Session, periodo_id: int, minimo: int, excluir_id: int | None = None) -> bool:
    """¿El periodo ya tiene una solicitud activa de al menos `minimo` días laborales seguidos?"""
    q = select(SolicitudVacaciones.id).where(
        SolicitudVacaciones.periodo_id == periodo_id, SolicitudVacaciones.estado.in_(ESTADOS_ACTIVOS),
        SolicitudVacaciones.dias_habiles >= minimo,
    )
    if excluir_id:
        q = q.where(SolicitudVacaciones.id != excluir_id)
    return db.scalar(q.limit(1)) is not None


def saldo_periodo(db: Session, p: PeriodoVacaciones, excluir_id: int | None = None, hoy: date | None = None,
                  aplicar_vencimiento: bool = True) -> PeriodoOut:
    """Saldo del periodo. Si ya venció (18 meses), el saldo no usado se reporta como perdido.

    `aplicar_vencimiento=False` lo usa el administrador para capturar vacaciones históricas.
    """
    hoy = hoy or date.today()
    usados = horas_por_estado(db, p.id, excluir_id)
    total = p.horas_otorgadas + (p.ajuste_horas or 0)
    disp = total - sum(usados.values())
    perdidas = reglas.horas_perdidas(disp, p.fecha_vencimiento, hoy) if aplicar_vencimiento else 0.0
    disp -= perdidas
    hd = p.horas_por_dia
    out = PeriodoOut.model_validate(p)
    out.horas_total = total
    out.horas_borrador = usados[BORRADOR]
    out.horas_solicitado = usados[SOLICITADO]
    out.horas_validado = usados[VALIDADO]
    out.horas_disponible = disp
    out.dias_total = round(total / hd, 2)
    out.dias_borrador = round(usados[BORRADOR] / hd, 2)
    out.dias_solicitado = round(usados[SOLICITADO] / hd, 2)
    out.dias_validado = round(usados[VALIDADO] / hd, 2)
    out.dias_disponible = round(disp / hd, 2)
    out.horas_perdidas = perdidas
    out.dias_perdidos = round(perdidas / hd, 2)
    out.minimo_dias = reglas.MIN_DIAS_SEGUIDOS["planta" if hd == reglas.HORAS_DIA["planta"] else "oficina"]
    out.bloque_cumplido = tiene_bloque_minimo(db, p.id, out.minimo_dias, excluir_id)
    out.vigente = p.fecha_vencimiento >= hoy
    return out


def usuario_out(u: Usuario) -> UsuarioOut:
    out = UsuarioOut.model_validate(u)
    out.turno_nombre = u.turno.nombre if u.turno else None
    out.grupo_nombre = u.grupo.nombre if u.grupo else None
    out.jefe_nombre = u.jefe.nombre if u.jefe else None
    out.tiene_foto = u.foto_tipo is not None
    out.microsoft_vinculado = bool(u.microsoft_oid)
    out.bloqueado = bool(u.bloqueado_hasta and u.bloqueado_hasta > datetime.now(timezone.utc).replace(tzinfo=None))
    out.antiguedad_anios = reglas.anios_cumplidos(u.fecha_ingreso, date.today())
    db = object_session(u)
    if db is not None and (u.es_jefe or es_admin(u)):
        out.total_a_cargo = db.scalar(
            select(func.count(Usuario.id)).where(Usuario.jefe_id == u.id, Usuario.activo.is_(True))) or 0
    return out


# ---------------- Jefes y permisos de acceso ----------------
def puede_aprobar(u: Usuario) -> bool:
    return u.activo and (u.es_jefe or es_admin(u))


def empleado_visible(db: Session, actor: Usuario, usuario_id: int | None) -> Usuario:
    """El propio usuario, un subordinado directo (si es jefe) o cualquiera (si es administrador)."""
    if not usuario_id or usuario_id == actor.id:
        return actor
    emp = db.get(Usuario, usuario_id)
    if not emp:
        raise HTTPException(404, "Empleado no encontrado")
    if es_admin(actor) or emp.jefe_id == actor.id:
        return emp
    # También el jefe elegido como aprobador en alguna solicitud del empleado
    asignado = db.scalar(select(SolicitudVacaciones.id).where(
        SolicitudVacaciones.usuario_id == emp.id, SolicitudVacaciones.aprobador_id == actor.id).limit(1)) or \
        db.scalar(select(Permiso.id).where(Permiso.usuario_id == emp.id, Permiso.aprobador_id == actor.id).limit(1))
    if not asignado:
        raise HTTPException(403, "Solo puedes consultar al personal que tienes a cargo")
    return emp


def puede_revisar(actor: Usuario, solicitud) -> bool:
    """El administrador o el jefe asignado como aprobador (nunca su propia solicitud)."""
    if es_admin(actor):
        return True
    return solicitud.aprobador_id == actor.id and solicitud.usuario_id != actor.id


def resolver_aprobador(db: Session, empleado: Usuario, aprobador_id: int | None) -> int | None:
    """Valida el jefe elegido; si no se indica se usa el jefe directo del empleado."""
    aprobador_id = aprobador_id or empleado.jefe_id
    if not aprobador_id:
        if es_admin(empleado):
            return None  # un administrador puede quedar en la bandeja general
        raise HTTPException(422, "Selecciona al jefe que aprobará la solicitud.")
    if aprobador_id == empleado.id:
        raise HTTPException(422, "No puedes ser el aprobador de tu propia solicitud.")
    jefe = db.get(Usuario, aprobador_id)
    if not jefe or not puede_aprobar(jefe):
        raise HTTPException(422, "El jefe seleccionado no puede aprobar solicitudes.")
    return jefe.id


def hay_traslape(db: Session, usuario_id: int, inicio: date, fin: date, excluir_id: int | None) -> bool:
    q = select(SolicitudVacaciones.id).where(
        SolicitudVacaciones.usuario_id == usuario_id,
        SolicitudVacaciones.estado.in_(ESTADOS_ACTIVOS),
        SolicitudVacaciones.fecha_inicio <= fin,
        SolicitudVacaciones.fecha_fin >= inicio,
    )
    if excluir_id:
        q = q.where(SolicitudVacaciones.id != excluir_id)
    return db.scalar(q.limit(1)) is not None
