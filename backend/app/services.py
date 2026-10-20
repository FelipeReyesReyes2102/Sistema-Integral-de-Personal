"""Servicios que combinan las reglas con la base de datos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from . import reglas
from .config import settings
from .models import (
    BORRADOR, ESTADOS_ACTIVOS, ROL_ADMIN, ROL_GERENCIA_GH, SOLICITADO, VALIDADO, AdminSede, Festivo, Permiso, PeriodoVacaciones,
    ReglaAntiguedad, SolicitudVacaciones, Usuario,
)
from .models import ROLES_ADMIN, es_admin  # noqa: F401
from .schemas import PeriodoOut, UsuarioOut
from .sedes import admin_permite


def reglas_de_sede(db: Session, sede_id: int | None) -> tuple[list[ReglaAntiguedad], bool]:
    """Filas de la tabla de antigüedad de la sede y si son propias (False = usa la de la sede principal)."""
    propias = db.scalars(select(ReglaAntiguedad).where(ReglaAntiguedad.sede_id == sede_id)
                         .order_by(ReglaAntiguedad.anios_desde)).all() if sede_id else []
    if propias:
        return list(propias), True
    from .sedes import sede_principal
    return list(db.scalars(select(ReglaAntiguedad).where(ReglaAntiguedad.sede_id == sede_principal(db).id)
                           .order_by(ReglaAntiguedad.anios_desde))), False


def tabla_antiguedad(db: Session, sede_id: int | None = None) -> list[tuple[int, int, int]]:
    rows, _ = reglas_de_sede(db, sede_id)
    if not rows:
        return reglas.TABLA_ANTIGUEDAD_DEFAULT
    return [(r.anios_desde, r.anios_hasta, r.dias) for r in rows]


@dataclass(frozen=True)
class Jornada:
    """Parámetros de la jornada de un empleado (de su tipo de jornada o, si no tiene, de su categoría)."""
    nombre: str
    horas_dia: int
    bloque_minimo: int
    usa_ciclo_grupo: bool
    descuento: str | None = None   # horas | dias | None (lo que diga la sede)
    por_horas: bool = False
    minimo_horas: int = 1

    @property
    def categoria(self) -> str:
        """Para los festivos que aplican solo a oficinas o solo a planta."""
        return "planta" if self.usa_ciclo_grupo else "oficina"


def jornada_de(usuario: Usuario) -> Jornada:
    t = usuario.tipo_jornada
    if t is not None:
        return Jornada(t.nombre, t.horas_dia, t.bloque_minimo, t.usa_ciclo_grupo, t.descuento, bool(t.por_horas),
                       t.minimo_horas or 1)
    cat = reglas.categoria(usuario.rol)
    return Jornada("Planta" if cat == "planta" else "Oficina", reglas.HORAS_DIA[cat], reglas.MIN_DIAS_SEGUIDOS[cat],
                   cat == "planta")


def usa_horas(usuario: Usuario) -> bool:
    """¿El saldo se lleva en horas (tabla × 8 h, cada día descuenta las horas de su jornada) o en días completos?
    Lo define el tipo de jornada; si no, la política de la sede."""
    d = jornada_de(usuario).descuento
    if d in ("horas", "dias"):
        return d == "horas"
    return usuario.sede.equivalencia_horas if usuario.sede is not None else True


def generacion(usuario: Usuario) -> str:
    g = usuario.sede.generacion_dias if usuario.sede is not None else None
    return g if g in reglas.GENERACIONES else "aniversario"


def meses_vigencia(usuario: Usuario) -> int:
    return usuario.sede.meses_vigencia if usuario.sede is not None and usuario.sede.meses_vigencia else \
        settings.meses_vigencia_periodo


def ciclo_de(usuario: Usuario) -> reglas.Ciclo:
    """Según su jornada: lunes a viernes, o el ciclo del grupo asignado (p. ej. 4×4)."""
    g = usuario.grupo
    if jornada_de(usuario).usa_ciclo_grupo and g is not None:
        return reglas.Ciclo(
            tipo=g.tipo_ciclo,
            dias_semana=reglas.parse_dias_semana(g.dias_semana),
            dias_trabajo=g.dias_trabajo,
            dias_descanso=g.dias_descanso,
            fecha_inicio=g.fecha_inicio_ciclo,
        )
    return reglas.Ciclo()


def consulta_festivos(usuario: Usuario, desde: date, hasta: date):
    """Festivos de la sede del empleado que aplican a su categoría."""
    return select(Festivo).where(Festivo.fecha >= desde, Festivo.fecha <= hasta, Festivo.sede_id == usuario.sede_id,
                                 Festivo.aplica_a.in_(["todos", jornada_de(usuario).categoria]))


def festivos_de(db: Session, usuario: Usuario, desde: date, hasta: date) -> set[date]:
    return {f.fecha for f in db.scalars(consulta_festivos(usuario, desde, hasta))}


def sincronizar_periodos(db: Session, usuario: Usuario, hoy: date | None = None) -> list[PeriodoVacaciones]:
    """Crea los periodos que falten y recalcula días/horas según la tabla y la categoría actual."""
    hoy = hoy or date.today()
    tabla = tabla_antiguedad(db, usuario.sede_id)
    jornada = jornada_de(usuario)
    equivalencia = usa_horas(usuario)
    existentes = {p.numero: p for p in usuario.periodos}
    cambios = False
    for pc in reglas.periodos_generados(usuario.fecha_ingreso, hoy, generacion(usuario), meses_vigencia(usuario),
                                        settings.vacaciones_al_cumplir_anio):
        dias = reglas.dias_por_antiguedad(pc.numero, tabla)
        horas = reglas.horas_otorgadas(dias) if equivalencia else float(dias * jornada.horas_dia)
        valores = dict(
            fecha_inicio=pc.fecha_inicio, fecha_vencimiento=pc.fecha_vencimiento, dias_ley=dias,
            horas_otorgadas=round(horas * pc.fraccion, 2), horas_por_dia=jornada.horas_dia,
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


def asignar_dias_disponibles(db: Session, usuario: Usuario, dias: float, hoy: date | None = None) -> list[tuple[str, float]]:
    """Fija el saldo disponible del empleado: primero el periodo actual (hasta sus días de ley) y el resto en los
    anteriores que sigan vigentes. Ajusta `ajuste_horas` de cada periodo; no hace commit. Devuelve el reparto."""
    hoy = hoy or date.today()
    vigentes = sorted((p for p in sincronizar_periodos(db, usuario, hoy) if p.fecha_vencimiento >= hoy
                       and p.fecha_inicio <= hoy),  # los periodos futuros solo guardan saldo negativo planeado
                      key=lambda p: p.fecha_inicio, reverse=True)
    hd = jornada_de(usuario).horas_dia
    if dias > 0 and not vigentes:
        raise HTTPException(422, "El empleado aún no tiene periodos de vacaciones vigentes: el primero se genera al "
                                 "cumplir un año de servicio.")
    maximo = sum(p.horas_otorgadas for p in vigentes) / hd
    if dias > maximo + 1e-9:
        detalle = ", ".join(f"{p.nombre}: {p.horas_otorgadas / hd:g}" for p in vigentes)
        raise HTTPException(422, f"El empleado puede tener como máximo {maximo:g} día(s) disponibles ({detalle}).")
    restante, reparto = dias * hd, []
    for p in vigentes:
        objetivo = min(restante, p.horas_otorgadas)
        restante -= objetivo
        actual = saldo_periodo(db, p, hoy=hoy).horas_disponible
        p.ajuste_horas = round((p.ajuste_horas or 0) + objetivo - actual, 4)
        p.nota_ajuste = "Saldo capturado en el alta o edición del empleado"
        reparto.append((p.nombre, objetivo / hd))
    return reparto


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
    out.minimo_dias = jornada_de(p.usuario).bloque_minimo if p.usuario is not None else \
        reglas.MIN_DIAS_SEGUIDOS["planta" if hd == reglas.HORAS_DIA["planta"] else "oficina"]
    out.bloque_cumplido = tiene_bloque_minimo(db, p.id, out.minimo_dias, excluir_id)
    out.vigente = p.fecha_vencimiento >= hoy
    return out


def requiere_gh(registro) -> bool:
    """¿La sede del empleado pide que GH valide después del jefe?"""
    sede = registro.usuario.sede if registro.usuario is not None else None
    if sede is None:
        return False
    return bool(sede.aprobacion_gh_permisos if isinstance(registro, Permiso) else sede.aprobacion_gh_vacaciones)


def aprobar(registro, actor: Usuario) -> bool:
    """Aprueba una solicitud de vacaciones o un permiso. Con dos niveles, la aprobación del jefe deja la solicitud
    pendiente de GH. Devuelve True si quedó validada (False si solo la aprobó el jefe)."""
    from datetime import datetime as _dt
    if requiere_gh(registro) and not es_admin(actor):
        if registro.aprobado_jefe_id:
            raise HTTPException(400, "Ya la aprobaste; falta la validación de GH.")
        registro.aprobado_jefe_id, registro.fecha_aprobado_jefe = actor.id, _dt.now()
        return False
    registro.estado, registro.revisado_por_id, registro.fecha_revision = VALIDADO, actor.id, _dt.now()
    return True


def usuario_out(u: Usuario) -> UsuarioOut:
    out = UsuarioOut.model_validate(u)
    out.turno_nombre = u.turno.nombre if u.turno else None
    out.sede_nombre = u.sede.nombre if u.sede else None
    out.tipo_jornada_nombre = jornada_de(u).nombre
    out.grupo_nombre = u.grupo.nombre if u.grupo else None
    out.jefe_nombre = u.jefe.nombre if u.jefe else None
    out.tiene_foto = u.foto_tipo is not None
    out.microsoft_vinculado = bool(u.microsoft_oid)
    out.bloqueado = bool(u.bloqueado_hasta and u.bloqueado_hasta > datetime.now(timezone.utc).replace(tzinfo=None))
    out.antiguedad_anios = reglas.anios_cumplidos(u.fecha_ingreso, date.today())
    db = object_session(u)
    if db is not None and u.rol == ROL_GERENCIA_GH:
        out.sedes_admin = sorted(db.scalars(select(AdminSede.sede_id).where(AdminSede.usuario_id == u.id)))
    if db is not None and (u.es_jefe or es_admin(u)):
        out.total_a_cargo = db.scalar(
            select(func.count(Usuario.id)).where(Usuario.jefe_id == u.id, Usuario.activo.is_(True))) or 0
    return out


# ---------------- Jefes y permisos de acceso ----------------
def puede_aprobar(u: Usuario) -> bool:
    return u.activo and (u.es_jefe or es_admin(u))


def puede_aprobar_a(jefe: Usuario, empleado_sede_id: int | None) -> bool:
    """Los jefes solo tienen a cargo personas de su propia sede (o de las sedes que administran)."""
    return puede_aprobar(jefe) and (jefe.sede_id == empleado_sede_id or admin_permite(jefe, empleado_sede_id))


def empleado_visible(db: Session, actor: Usuario, usuario_id: int | None) -> Usuario:
    """El propio usuario, un subordinado directo (si es jefe) o cualquiera (si es administrador)."""
    if not usuario_id or usuario_id == actor.id:
        return actor
    emp = db.get(Usuario, usuario_id)
    if not emp:
        raise HTTPException(404, "Empleado no encontrado")
    if (es_admin(actor) and admin_permite(actor, emp.sede_id)) or emp.jefe_id == actor.id:
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
        return admin_permite(actor, solicitud.usuario.sede_id if solicitud.usuario else None)
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
    if not puede_aprobar_a(jefe, empleado.sede_id):
        raise HTTPException(422, "El jefe seleccionado pertenece a otra sede.")
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
