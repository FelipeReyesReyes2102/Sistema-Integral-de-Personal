"""Rotación de turnos entre grupos y aviso semanal por correo.

Con la rotación activa, cada grupo participante cambia de turno cada `semanas` semanas a partir de
`fecha_inicio`, siguiendo el orden de `turnos_orden` y empezando en su `rotacion_turno_inicial_id`.
El turno vigente se copia a `Usuario.turno_id` (sincronización diaria) para que el resto del sistema
(permisos, avisos a caseta, jornada) use siempre el turno actual.

Con la rotación desactivada, todos los integrantes de los grupos pasan al `turno_unico_id`.
"""
import html
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import correo
from .database import SessionLocal
from .models import Grupo, NotificacionCorreo, RotacionTurnos, Turno, Usuario, correo_contacto
from .security import ahora

log = logging.getLogger("sip.rotacion")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def config(db: Session) -> RotacionTurnos:
    cfg = db.get(RotacionTurnos, 1)
    if cfg is None:
        cfg = RotacionTurnos(id=1, activo=False, semanas=1, turnos_orden="", aviso_activo=False, aviso_hora=12)
        db.add(cfg)
        db.commit()
    return cfg


def orden(cfg: RotacionTurnos) -> list[int]:
    return [int(x) for x in (cfg.turnos_orden or "").split(",") if x.strip().isdigit()]


def numero_periodo(cfg: RotacionTurnos, fecha: date) -> int:
    return (fecha - cfg.fecha_inicio).days // (7 * max(cfg.semanas, 1))


def inicio_periodo(cfg: RotacionTurnos, fecha: date) -> date:
    return cfg.fecha_inicio + timedelta(days=numero_periodo(cfg, fecha) * 7 * max(cfg.semanas, 1))


def turno_de_grupo(cfg: RotacionTurnos, grupo: Grupo, fecha: date) -> int | None:
    """Id del turno que le toca al grupo en la fecha (o None si no rota)."""
    ids = orden(cfg)
    if not (cfg.activo and cfg.fecha_inicio and grupo.en_rotacion and ids and grupo.rotacion_turno_inicial_id in ids):
        return None
    return ids[(ids.index(grupo.rotacion_turno_inicial_id) + numero_periodo(cfg, fecha)) % len(ids)]


def turno_efectivo(db: Session, usuario: Usuario, fecha: date) -> Turno | None:
    cfg = config(db)
    if usuario.grupo is not None:
        tid = turno_de_grupo(cfg, usuario.grupo, fecha)
        if tid:
            return db.get(Turno, tid)
    return usuario.turno


def sincronizar(db: Session, hoy: date | None = None) -> int:
    """Copia a cada integrante el turno que le toca hoy. Devuelve cuántos usuarios cambiaron."""
    hoy = hoy or date.today()
    cfg = config(db)
    cambios = 0
    if cfg.activo:
        for g in db.scalars(select(Grupo).where(Grupo.en_rotacion.is_(True))):
            tid = turno_de_grupo(cfg, g, hoy)
            if not tid:
                continue
            for u in db.scalars(select(Usuario).where(Usuario.grupo_id == g.id, Usuario.activo.is_(True))):
                if u.turno_id != tid:
                    u.turno_id = tid
                    cambios += 1
    cfg.ultima_sincronizacion = hoy
    db.commit()
    return cambios


def aplicar_turno_unico(db: Session, turno_id: int, grupo_ids: list[int]) -> int:
    """Al desactivar la rotación: todos los integrantes de los grupos quedan en un solo turno."""
    cambios = 0
    for u in db.scalars(select(Usuario).where(Usuario.grupo_id.in_(grupo_ids), Usuario.activo.is_(True))):
        if u.turno_id != turno_id:
            u.turno_id = turno_id
            cambios += 1
    db.commit()
    return cambios


def proximo_lunes(hoy: date) -> date:
    return hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)


def semanas_de(db: Session, usuario: Usuario, desde: date, n: int = 6) -> list[dict]:
    """Turno por semana (lunes a domingo) a partir del lunes de `desde`."""
    lunes = desde - timedelta(days=desde.weekday())
    res = []
    for i in range(n):
        ini = lunes + timedelta(weeks=i)
        t = turno_efectivo(db, usuario, ini)
        res.append({"desde": ini, "hasta": ini + timedelta(days=6), "turno": _turno_dict(t)})
    return res


def _turno_dict(t: Turno | None) -> dict | None:
    if not t:
        return None
    return {"id": t.id, "nombre": t.nombre, "hora_entrada": t.hora_entrada.strftime("%H:%M"),
            "hora_salida": t.hora_salida.strftime("%H:%M"), "horas_jornada": t.horas_jornada}


# ---------------- Aviso semanal por correo ----------------
def _mensaje(usuario: Usuario, actual: dict | None, siguiente: dict | None, lunes: date) -> tuple[str, str, str]:
    def txt(t):
        return f"{t['nombre']} ({t['hora_entrada']} - {t['hora_salida']})" if t else "Sin turno asignado"
    cambia = (actual or {}).get("id") != (siguiente or {}).get("id")
    asunto = f"Tu turno de la próxima semana: {siguiente['nombre'] if siguiente else 'sin turno'} (desde el {lunes:%d/%m})"
    filas = [("Empleado", usuario.nombre), ("No. de nómina", usuario.numero_empleado),
             ("Grupo", usuario.grupo.nombre if usuario.grupo else ""),
             ("Esta semana", txt(actual)),
             (f"Próxima semana ({lunes:%d/%m} al {lunes + timedelta(days=6):%d/%m})", txt(siguiente))]
    nota = ("Hay CAMBIO de turno a partir del lunes." if cambia else "Continúas en el mismo turno.") + \
           " Puedes consultar tus próximos turnos en el sistema de vacaciones y permisos."
    color = "#e67e22" if cambia else "#1f4a86"
    cuerpo = correo._plantilla("CAMBIO DE TURNO" if cambia else "TURNO DE LA PRÓXIMA SEMANA", color, filas, nota)
    cuerpo = cuerpo.replace("SIP-O · AVISO A CASETA", "SIP-O · AVISO DE TURNO")
    texto = f"{asunto}\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, cuerpo, texto


def enviar_avisos(db: Session, hoy: date | None = None) -> dict:
    """Envía a cada integrante de los grupos en rotación su turno de la próxima semana."""
    hoy = hoy or date.today()
    cfg = config(db)
    if not cfg.activo:
        return {"enviados": 0, "errores": 0, "omitidos": 0, "motivo": "La rotación de turnos está desactivada."}
    ccfg = correo.cargar(db)
    lunes = proximo_lunes(hoy)
    enviados = errores = omitidos = 0
    grupos = [g.id for g in db.scalars(select(Grupo).where(Grupo.en_rotacion.is_(True)))]
    for u in db.scalars(select(Usuario).where(Usuario.grupo_id.in_(grupos), Usuario.activo.is_(True)).order_by(Usuario.nombre)):
        destino = correo_contacto(u)  # planta: correo personal
        if not destino or not correo.EMAIL.match(destino):
            omitidos += 1
            continue
        actual = _turno_dict(turno_efectivo(db, u, hoy))
        siguiente = _turno_dict(turno_efectivo(db, u, lunes))
        asunto, cuerpo, texto = _mensaje(u, actual, siguiente, lunes)
        n = NotificacionCorreo(fecha=ahora(), evento="turno_semanal", destinatarios=destino, asunto=asunto[:255])
        db.add(n)
        db.commit()
        correo._registrar_y_enviar(db, n, ccfg, cuerpo, texto)
        if n.estado == "enviado":
            enviados += 1
        else:
            errores += 1
    return {"enviados": enviados, "errores": errores, "omitidos": omitidos, "semana": lunes}


# ---------------- Tarea programada ----------------
def tarea_programada(ahora_local: datetime | None = None):
    """Se ejecuta periódicamente: sincroniza turnos una vez al día y envía el aviso de los viernes."""
    ahora_local = ahora_local or datetime.now()
    hoy = ahora_local.date()
    with SessionLocal() as db:
        cfg = config(db)
        if cfg.ultima_sincronizacion != hoy:
            cambios = sincronizar(db, hoy)
            if cambios:
                log.info("Rotación de turnos: %s usuario(s) cambiaron de turno", cambios)
        if (cfg.activo and cfg.aviso_activo and hoy.weekday() == 4 and ahora_local.hour >= cfg.aviso_hora
                and cfg.ultimo_aviso != hoy):
            cfg.ultimo_aviso = hoy  # se marca antes de enviar para no duplicar
            db.commit()
            res = enviar_avisos(db, hoy)
            log.info("Aviso semanal de turnos: %s", res)


def describir(cfg: RotacionTurnos, turnos: dict[int, str]) -> str:
    if not cfg.activo:
        return "Rotación desactivada"
    nombres = " → ".join(turnos.get(i, "?") for i in orden(cfg))
    dia = DIAS[cfg.fecha_inicio.weekday()] if cfg.fecha_inicio else "?"
    cada = "cada semana" if cfg.semanas == 1 else f"cada {cfg.semanas} semanas"
    return html.escape(f"{nombres}, {cada}, cambio los {dia}")
