from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import reglas
from ..database import get_db
from ..models import (
    BORRADOR, CANCELADO, RECHAZADO, ROL_ADMIN, SOLICITADO, VALIDADO, PeriodoVacaciones, SolicitudVacaciones,
    Usuario,
)
from ..models import ROLES_ADMIN, es_admin  # noqa: F401
from ..models import Festivo
from ..schemas import (
    CalculoIn, CalculoOut, DiaExcluido, DiasLaboralesIn, DiasLaboralesOut, RechazoIn, TramoPeriodo, VacacionesIn,
    VacacionesOut,
)
from ..security import get_current_user
from ..services import (
    ciclo_de, empleado_visible, festivos_de, hay_traslape, puede_revisar, resolver_aprobador, saldo_periodo,
    sincronizar_periodos,
)

router = APIRouter(prefix="/api/vacaciones", tags=["vacaciones"])


def _out(s: SolicitudVacaciones) -> VacacionesOut:
    o = VacacionesOut.model_validate(s)
    o.usuario_nombre = s.usuario.nombre if s.usuario else None
    o.periodo_nombre = s.periodo.nombre if s.periodo else None
    o.aprobador_nombre = s.aprobador.nombre if s.aprobador else None
    o.revisado_por_nombre = s.revisado_por.nombre if s.revisado_por else None
    o.tiene_firma = bool(s.firma)
    return o


FALTA_FIRMA = "Firma la solicitud para poder enviarla."


def _destino(db: Session, user: Usuario, usuario_id: int | None) -> Usuario:
    """Para crear solicitudes: el propio usuario, o cualquiera si es administrador."""
    if usuario_id and usuario_id != user.id:
        if not es_admin(user):
            raise HTTPException(403, "Solo el administrador puede capturar solicitudes de otros empleados")
        u = db.get(Usuario, usuario_id)
        if not u:
            raise HTTPException(404, "Empleado no encontrado")
        return u
    return user


def _calcular(db: Session, empleado: Usuario, actor: Usuario, periodo_id: int, inicio: date, fin: date,
              excluir_id: int | None = None):
    sincronizar_periodos(db, empleado)
    periodo = db.get(PeriodoVacaciones, periodo_id)
    if not periodo or periodo.usuario_id != empleado.id:
        raise HTTPException(404, "Periodo no encontrado para este empleado")
    saldo = saldo_periodo(db, periodo, excluir_id=excluir_id, aplicar_vencimiento=not es_admin(actor))
    cat = reglas.categoria(empleado.rol)
    res = reglas.validar_vacaciones(
        cat=cat, inicio=inicio, fin=fin, ciclo=ciclo_de(empleado),
        festivos=festivos_de(db, empleado, inicio, fin),
        horas_disponibles=saldo.horas_disponible,
        periodo_inicio=periodo.fecha_inicio, periodo_vencimiento=periodo.fecha_vencimiento,
        hoy=date.today(), permitir_pasado=es_admin(actor), tiene_bloque=saldo.bloque_cumplido,
    )
    if fin >= inicio and hay_traslape(db, empleado.id, inicio, fin, excluir_id):
        res.errores.append("Ya tienes otra solicitud de vacaciones que se cruza con esas fechas.")
    if cat == "planta" and empleado.grupo is None:
        res.advertencias.append("No tienes grupo asignado; se calcularon días de lunes a viernes.")
    return periodo, saldo, res


def _general(db: Session, empleado: Usuario, actor: Usuario, inicio: date, fin: date, excluir_id: int | None = None):
    """Modo general: reparte los días laborales del rango entre los periodos vigentes, primero el más antiguo
    (para no perder días al cumplir 18 meses). Devuelve los tramos [(periodo, desde, hasta, resultado)], el
    resultado global y el saldo total."""
    sincronizar_periodos(db, empleado)
    cat = reglas.categoria(empleado.rol)
    hd = reglas.HORAS_DIA[cat]
    if fin < inicio:
        return [], reglas.ResultadoValidacion(0, 0, ["La fecha final no puede ser anterior a la inicial."], [], []), 0.0
    fechas = reglas.dias_laborales(inicio, fin, ciclo_de(empleado), festivos_de(db, empleado, inicio, fin))
    # Solo los periodos vigentes en alguna fecha del rango (el administrador puede capturar fechas pasadas)
    periodos = db.scalars(select(PeriodoVacaciones).where(
        PeriodoVacaciones.usuario_id == empleado.id, PeriodoVacaciones.fecha_vencimiento >= inicio,
        PeriodoVacaciones.fecha_inicio <= fin).order_by(PeriodoVacaciones.fecha_inicio)).all()
    capacidad, horas_total = {}, 0.0
    for p in periodos:
        disp = saldo_periodo(db, p, excluir_id=excluir_id, aplicar_vencimiento=not es_admin(actor)).horas_disponible
        if disp > 0:
            capacidad[p.id] = int(disp // hd + 1e-9)
            horas_total += disp
    disponibles = sum(capacidad.values())

    # Cada día laboral se toma del periodo más antiguo que tenga saldo y esté vigente en esa fecha
    tramos: list[list] = []
    sin_saldo = 0
    for d in fechas:
        p = next((p for p in periodos if capacidad.get(p.id, 0) > 0 and p.fecha_inicio <= d <= p.fecha_vencimiento), None)
        if p is None:
            sin_saldo += 1
            continue
        capacidad[p.id] -= 1
        if tramos and tramos[-1][0].id == p.id:
            tramos[-1][2] = d
        else:
            tramos.append([p, d, d])

    errores, advertencias, resultado = [], [], []
    if not fechas:
        errores.append("El rango seleccionado no contiene días laborales.")
    elif sin_saldo:
        errores.append(f"Saldo insuficiente: solicitas {len(fechas)} día(s) y tienes {disponibles} día(s) "
                       "disponibles entre tus periodos vigentes.")
    else:
        varios = len(tramos) > 1
        for p, desde, hasta in tramos:
            _, _, res = _calcular(db, empleado, actor, p.id, desde, hasta, excluir_id)
            pref = f"{p.nombre}: " if varios else ""
            errores += [pref + e for e in res.errores]
            advertencias += [pref + a for a in res.advertencias]
            resultado.append((p, desde, hasta, res))
    if not fechas or sin_saldo:
        if not es_admin(actor) and inicio < date.today():
            errores.append("No es posible solicitar vacaciones en fechas pasadas.")
        if fin >= inicio and hay_traslape(db, empleado.id, inicio, fin, excluir_id):
            errores.append("Ya tienes otra solicitud de vacaciones que se cruza con esas fechas.")
    total = reglas.ResultadoValidacion(len(fechas), float(len(fechas) * hd), list(dict.fromkeys(errores)),
                                       list(dict.fromkeys(advertencias)), fechas)
    return resultado, total, horas_total


def _crear_solicitudes(db: Session, empleado: Usuario, data: VacacionesIn, tramos, aprobador_id: int | None,
                       existente: SolicitudVacaciones | None = None) -> list[SolicitudVacaciones]:
    """Una solicitud por tramo; si son varias se marcan como "Parte i de n" en el comentario."""
    creadas = []
    for i, (p, desde, hasta, res) in enumerate(tramos):
        comentario = data.comentario
        if len(tramos) > 1:
            comentario = f"[Parte {i + 1} de {len(tramos)}] {data.comentario or ''}".strip()
        s = existente if (i == 0 and existente) else SolicitudVacaciones(usuario_id=empleado.id)
        s.periodo_id, s.fecha_inicio, s.fecha_fin = p.id, desde, hasta
        s.dias_habiles, s.horas, s.comentario, s.aprobador_id = res.dias_habiles, res.horas, comentario, aprobador_id
        if data.firma:
            s.firma = data.firma
        s.estado = SOLICITADO if data.enviar else BORRADOR
        if s.id is None:
            db.add(s)
        creadas.append(s)
    return creadas


@router.post("/dias-laborales", response_model=DiasLaboralesOut)
def dias_laborales(data: DiasLaboralesIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Cuenta los días a disfrutar de un rango: excluye fines de semana (o descansos del ciclo de planta) y festivos."""
    empleado = _destino(db, user, data.usuario_id)
    if data.fecha_fin < data.fecha_inicio:
        raise HTTPException(422, "La fecha final no puede ser anterior a la inicial.")
    if (data.fecha_fin - data.fecha_inicio).days > 366:
        raise HTTPException(422, "El rango no puede ser mayor a un año.")
    cat = reglas.categoria(empleado.rol)
    ciclo = ciclo_de(empleado)
    nombres = {f.fecha: f.nombre for f in db.scalars(select(Festivo).where(
        Festivo.fecha >= data.fecha_inicio, Festivo.fecha <= data.fecha_fin, Festivo.aplica_a.in_(["todos", cat])))}
    fechas = reglas.dias_laborales(data.fecha_inicio, data.fecha_fin, ciclo, set(nombres))
    excluidos, d = [], data.fecha_inicio
    laborales = set(fechas)
    while d <= data.fecha_fin:
        if d not in laborales:
            if d in nombres:
                motivo = f"Festivo: {nombres[d]}"
            elif ciclo.tipo == "semanal" and d.weekday() >= 5:
                motivo = "Fin de semana"
            else:
                motivo = "Día de descanso"
            excluidos.append(DiaExcluido(fecha=d, motivo=motivo))
        d += timedelta(days=1)
    hd = reglas.HORAS_DIA[cat]
    return DiasLaboralesOut(dias_habiles=len(fechas), horas=float(len(fechas) * hd), horas_por_dia=hd,
                            fechas=fechas, excluidos=excluidos)


@router.post("/calcular", response_model=CalculoOut)
def calcular(data: CalculoIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Vista previa: días laborales, horas y reglas incumplidas, sin guardar."""
    empleado = _destino(db, user, data.usuario_id)
    if data.periodo_id is None:
        tramos, res, horas_total = _general(db, empleado, user, data.fecha_inicio, data.fecha_fin, data.excluir_id)
        cat = reglas.categoria(empleado.rol)
        return CalculoOut(
            dias_habiles=res.dias_habiles, horas=res.horas, errores=res.errores, advertencias=res.advertencias,
            fechas=res.fechas, horas_disponible=horas_total, dias_disponible=reglas.horas_a_dias(horas_total, cat),
            minimo_dias=reglas.MIN_DIAS_SEGUIDOS[cat],
            reparto=[TramoPeriodo(periodo_id=p.id, periodo_nombre=p.nombre, fecha_inicio=a, fecha_fin=b, dias=r.dias_habiles)
                     for p, a, b, r in tramos],
        )
    _, saldo, res = _calcular(db, empleado, user, data.periodo_id, data.fecha_inicio, data.fecha_fin, data.excluir_id)
    return CalculoOut(
        dias_habiles=res.dias_habiles, horas=res.horas, errores=res.errores, advertencias=res.advertencias,
        fechas=res.fechas, horas_disponible=saldo.horas_disponible, dias_disponible=saldo.dias_disponible,
        minimo_dias=reglas.MIN_DIAS_SEGUIDOS[reglas.categoria(empleado.rol)],
    )


@router.get("", response_model=list[VacacionesOut])
def listar(estado: str | None = None, usuario_id: int | None = None, todos: bool = False,
           por_aprobar: bool = False, periodo_id: int | None = None,
           db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """
    - Sin parámetros: mis solicitudes.
    - `usuario_id`: solicitudes de un subordinado (jefe) o de cualquiera (administrador).
    - `por_aprobar=true`: solicitudes donde soy el jefe aprobador.
    - `todos=true`: todas (solo administrador).
    """
    q = select(SolicitudVacaciones).order_by(SolicitudVacaciones.fecha_inicio.desc())
    if todos and es_admin(user):
        pass
    elif por_aprobar:
        q = q.where(SolicitudVacaciones.aprobador_id == user.id, SolicitudVacaciones.usuario_id != user.id)
    else:
        q = q.where(SolicitudVacaciones.usuario_id == empleado_visible(db, user, usuario_id).id)
    if estado:
        q = q.where(SolicitudVacaciones.estado == estado)
    if periodo_id:
        q = q.where(SolicitudVacaciones.periodo_id == periodo_id)
    return [_out(s) for s in db.scalars(q)]


@router.post("", response_model=VacacionesOut, status_code=201)
def crear(data: VacacionesIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    empleado = _destino(db, user, data.usuario_id)
    aprobador_id = resolver_aprobador(db, empleado, data.aprobador_id)
    if data.enviar and not data.firma:
        raise HTTPException(422, FALTA_FIRMA)
    if data.periodo_id is None:
        tramos, res, _ = _general(db, empleado, user, data.fecha_inicio, data.fecha_fin)
        if not res.ok:
            raise HTTPException(422, " ".join(res.errores))
        creadas = _crear_solicitudes(db, empleado, data, tramos, aprobador_id)
        db.commit()
        return _out(creadas[0])
    periodo, _, res = _calcular(db, empleado, user, data.periodo_id, data.fecha_inicio, data.fecha_fin)
    if not res.ok:
        raise HTTPException(422, " ".join(res.errores))
    s = SolicitudVacaciones(
        usuario_id=empleado.id, periodo_id=periodo.id, fecha_inicio=data.fecha_inicio, fecha_fin=data.fecha_fin,
        dias_habiles=res.dias_habiles, horas=res.horas, comentario=data.comentario, aprobador_id=aprobador_id,
        firma=data.firma,
        estado=SOLICITADO if data.enviar else BORRADOR,
    )
    db.add(s)
    db.commit()
    return _out(s)


def _obtener(db: Session, sid: int, user: Usuario) -> SolicitudVacaciones:
    s = db.get(SolicitudVacaciones, sid)
    visible = s and (s.usuario_id == user.id or es_admin(user) or s.aprobador_id == user.id
                     or s.usuario.jefe_id == user.id)
    if not visible:
        raise HTTPException(404, "Solicitud no encontrada")
    return s


def _es_dueno_o_admin(s: SolicitudVacaciones, user: Usuario):
    if s.usuario_id != user.id and not es_admin(user):
        raise HTTPException(403, "Solo el solicitante puede modificar esta solicitud")


@router.put("/{sid}", response_model=VacacionesOut)
def editar(sid: int, data: VacacionesIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _obtener(db, sid, user)
    _es_dueno_o_admin(s, user)
    if s.estado != BORRADOR:
        raise HTTPException(400, "Solo se pueden editar solicitudes en borrador")
    aprobador_id = resolver_aprobador(db, s.usuario, data.aprobador_id)
    if data.enviar and not (data.firma or s.firma):
        raise HTTPException(422, FALTA_FIRMA)
    if data.periodo_id is None:
        tramos, res, _ = _general(db, s.usuario, user, data.fecha_inicio, data.fecha_fin, excluir_id=s.id)
        if not res.ok:
            raise HTTPException(422, " ".join(res.errores))
        if not data.firma and s.firma:
            data.firma = s.firma
        _crear_solicitudes(db, s.usuario, data, tramos, aprobador_id, existente=s)
        db.commit()
        return _out(s)
    _, _, res = _calcular(db, s.usuario, user, data.periodo_id, data.fecha_inicio, data.fecha_fin, excluir_id=s.id)
    if not res.ok:
        raise HTTPException(422, " ".join(res.errores))
    s.periodo_id, s.fecha_inicio, s.fecha_fin = data.periodo_id, data.fecha_inicio, data.fecha_fin
    s.dias_habiles, s.horas, s.comentario = res.dias_habiles, res.horas, data.comentario
    s.aprobador_id = aprobador_id
    if data.firma:
        s.firma = data.firma
    if data.enviar:
        if not s.firma:
            raise HTTPException(422, FALTA_FIRMA)
        s.estado = SOLICITADO
    db.commit()
    return _out(s)


@router.post("/{sid}/enviar", response_model=VacacionesOut)
def enviar(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _obtener(db, sid, user)
    _es_dueno_o_admin(s, user)
    if s.estado != BORRADOR:
        raise HTTPException(400, "La solicitud ya fue enviada")
    if not s.firma:
        raise HTTPException(422, "Abre la solicitud y fírmala para poder enviarla.")
    s.aprobador_id = resolver_aprobador(db, s.usuario, s.aprobador_id)
    _, _, res = _calcular(db, s.usuario, user, s.periodo_id, s.fecha_inicio, s.fecha_fin, excluir_id=s.id)
    if not res.ok:
        raise HTTPException(422, " ".join(res.errores))
    s.estado = SOLICITADO
    db.commit()
    return _out(s)


@router.get("/{sid}", response_model=VacacionesOut)
def detalle(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return _out(_obtener(db, sid, user))


@router.get("/{sid}/firma")
def firma(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return {"firma": _obtener(db, sid, user).firma}


@router.post("/{sid}/cancelar", response_model=VacacionesOut)
def cancelar(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _obtener(db, sid, user)
    if s.usuario_id == user.id or es_admin(user):
        permitido = {BORRADOR, SOLICITADO} | ({VALIDADO} if es_admin(user) else set())
    elif puede_revisar(user, s):
        permitido = {VALIDADO}  # el jefe puede revertir una aprobación suya
    else:
        raise HTTPException(403, "No autorizado")
    if s.estado not in permitido:
        raise HTTPException(400, "Esta solicitud ya no se puede cancelar; contacta a tu jefe o al administrador")
    s.estado = CANCELADO
    db.commit()
    return _out(s)


@router.delete("/{sid}", status_code=204)
def eliminar(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _obtener(db, sid, user)
    _es_dueno_o_admin(s, user)
    if s.estado != BORRADOR:
        raise HTTPException(400, "Solo se pueden eliminar borradores; usa cancelar")
    db.delete(s)
    db.commit()


def _revisable(db: Session, sid: int, user: Usuario) -> SolicitudVacaciones:
    s = _obtener(db, sid, user)
    if not puede_revisar(user, s):
        raise HTTPException(403, "Solo el jefe asignado o el administrador puede aprobar esta solicitud")
    if s.estado != SOLICITADO:
        raise HTTPException(400, "Solo se pueden revisar solicitudes pendientes")
    return s


@router.post("/{sid}/validar", response_model=VacacionesOut)
def validar(sid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _revisable(db, sid, user)
    s.estado, s.revisado_por_id, s.fecha_revision = VALIDADO, user.id, datetime.now()
    db.commit()
    return _out(s)


@router.post("/{sid}/rechazar", response_model=VacacionesOut)
def rechazar(sid: int, data: RechazoIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    s = _revisable(db, sid, user)
    s.estado, s.motivo_rechazo = RECHAZADO, data.motivo
    s.revisado_por_id, s.fecha_revision = user.id, datetime.now()
    db.commit()
    return _out(s)
