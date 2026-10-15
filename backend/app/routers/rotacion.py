"""Rotación de turnos (administrador) y consulta del turno propio (todos)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import horarios, rotacion
from ..database import get_db
from ..models import Grupo, Turno, Usuario
from ..security import ahora, auditar, get_current_user, require_admin
from ..sedes import Alcance, alcance, hoy_de

router = APIRouter(prefix="/api", tags=["rotación de turnos"])


class GrupoRotacionIn(BaseModel):
    grupo_id: int
    en_rotacion: bool
    turno_inicial_id: int | None = None


class RotacionIn(BaseModel):
    activo: bool
    fecha_inicio: date | None = None
    semanas: int = Field(1, ge=1, le=12)
    turnos_orden: list[int] = []
    turno_unico_id: int | None = None
    aviso_activo: bool = False
    aviso_hora: int = Field(12, ge=0, le=23)
    grupos: list[GrupoRotacionIn] = []


def _estado(db: Session, sede_id: int | None) -> dict:
    cfg = rotacion.config(db, sede_id)
    turnos = {t.id: t for t in db.scalars(select(Turno).where(Turno.sede_id == sede_id).order_by(Turno.nombre))}
    grupos = db.scalars(select(Grupo).where(Grupo.sede_id == sede_id).order_by(Grupo.nombre)).all()
    miembros = dict(db.execute(select(Usuario.grupo_id, func.count(Usuario.id))
                               .where(Usuario.activo.is_(True)).group_by(Usuario.grupo_id)).all())
    vista = []
    if cfg.activo and cfg.fecha_inicio:
        ini = rotacion.inicio_periodo(cfg, max(date.today(), cfg.fecha_inicio))
        for i in range(8):
            desde = ini + timedelta(weeks=i * cfg.semanas)
            vista.append({
                "desde": desde, "hasta": desde + timedelta(days=7 * cfg.semanas - 1),
                "grupos": {g.id: (turnos[t].nombre if (t := rotacion.turno_de_grupo(cfg, g, desde)) in turnos else None)
                           for g in grupos if g.en_rotacion},
            })
    return {
        "activo": cfg.activo, "fecha_inicio": cfg.fecha_inicio, "semanas": cfg.semanas,
        "turnos_orden": rotacion.orden(cfg), "turno_unico_id": cfg.turno_unico_id,
        "aviso_activo": cfg.aviso_activo, "aviso_hora": cfg.aviso_hora, "ultimo_aviso": cfg.ultimo_aviso,
        "descripcion": rotacion.describir(cfg, {i: t.nombre for i, t in turnos.items()}),
        "turnos": [{"id": t.id, "nombre": t.nombre, "hora_entrada": t.hora_entrada.strftime("%H:%M"),
                    "hora_salida": t.hora_salida.strftime("%H:%M")} for t in turnos.values()],
        "grupos": [{"id": g.id, "nombre": g.nombre, "color": g.color, "en_rotacion": g.en_rotacion,
                    "turno_inicial_id": g.rotacion_turno_inicial_id, "miembros": miembros.get(g.id, 0),
                    "turno_actual": (turnos[t].nombre if (t := rotacion.turno_de_grupo(cfg, g, date.today())) in turnos else None)}
                   for g in grupos],
        "vista_previa": vista,
    }


@router.get("/rotacion")
def obtener(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    return _estado(db, alc.defecto)


@router.put("/rotacion")
def guardar(data: RotacionIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
            alc: Alcance = Depends(alcance)):
    sede_id = alc.defecto
    turnos_validos = {t.id for t in db.scalars(select(Turno).where(Turno.sede_id == sede_id))}
    orden = [t for t in data.turnos_orden if t in turnos_validos]
    participantes = [g for g in data.grupos if g.en_rotacion]
    errores = []
    if data.activo:
        if not data.fecha_inicio:
            errores.append("Indica la fecha en que inicia la rotación (día de cambio de turno).")
        if len(set(orden)) < 2:
            errores.append("Selecciona al menos dos turnos para rotar.")
        if len(participantes) < 1:
            errores.append("Selecciona los grupos que rotan.")
        for g in participantes:
            if g.turno_inicial_id not in orden:
                errores.append("Cada grupo que rota debe tener un turno inicial de los turnos en rotación.")
                break
    elif data.turno_unico_id not in turnos_validos:
        errores.append("Al desactivar la rotación elige el turno único para todo el personal de los grupos.")
    if errores:
        raise HTTPException(422, " ".join(errores))

    cfg = rotacion.config(db, sede_id)
    estaba_activo = cfg.activo
    grupos = {g.id: g for g in db.scalars(select(Grupo).where(Grupo.sede_id == sede_id))}
    for g in data.grupos:
        if g.grupo_id in grupos:
            grupos[g.grupo_id].en_rotacion = g.en_rotacion
            grupos[g.grupo_id].rotacion_turno_inicial_id = g.turno_inicial_id if g.en_rotacion else None
    cfg.activo, cfg.fecha_inicio, cfg.semanas = data.activo, data.fecha_inicio, data.semanas
    cfg.turnos_orden = ",".join(str(t) for t in dict.fromkeys(orden))
    cfg.turno_unico_id = data.turno_unico_id
    cfg.aviso_activo, cfg.aviso_hora = data.aviso_activo, data.aviso_hora
    cfg.actualizado = ahora()
    db.commit()

    if data.activo:
        cambios = rotacion.sincronizar(db, sede_id)
        detalle = f"rotación activa · {cambios} usuario(s) actualizados"
    else:
        # Todos los integrantes de los grupos (los que rotaban y los marcados) quedan en un solo turno
        ids = list({g.grupo_id for g in data.grupos if g.grupo_id in grupos} | {gid for gid, g in grupos.items() if g.en_rotacion})
        cambios = rotacion.aplicar_turno_unico(db, data.turno_unico_id, ids)
        detalle = f"rotación {'desactivada' if estaba_activo else 'inactiva'} · turno único · {cambios} usuario(s)"
    auditar(db, "rotacion_turnos", actor_id=admin.id, detalle=detalle, request=request)
    db.commit()
    return {**_estado(db, sede_id), "usuarios_actualizados": cambios}


@router.post("/rotacion/avisos")
def enviar_avisos(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    """Envía ahora el correo con el turno de la próxima semana (normalmente sale solo cada viernes)."""
    return rotacion.enviar_avisos(db, alc.defecto)


@router.get("/turnos/horario")
def horario(fecha: date, usuario_id: int | None = None, db: Session = Depends(get_db),
            user: Usuario = Depends(get_current_user)):
    """Horario efectivo del empleado en una fecha (incluye horarios por día y especiales como Short Friday)."""
    from ..services import empleado_visible
    u = empleado_visible(db, user, usuario_id)
    t = rotacion.turno_efectivo(db, u, fecha)
    h = horarios.horario_de(t, fecha)
    if not h:
        return {"turno": None, "fecha": fecha}
    return {"turno": t.nombre, "fecha": fecha, "entrada": h["entrada"].strftime("%H:%M"),
            "salida": h["salida"].strftime("%H:%M"), "horas": h["horas"], "especial": h["especial"]}


@router.get("/turnos/mi-turno")
def mi_turno(usuario_id: int | None = None, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    from ..services import empleado_visible
    u = empleado_visible(db, user, usuario_id)
    cfg = rotacion.config(db, u.sede_id)
    hoy = hoy_de(u)
    rota = bool(cfg.activo and u.grupo and u.grupo.en_rotacion)
    semanas = rotacion.semanas_de(db, u, hoy, 6)
    proximo_cambio = None
    if rota and cfg.fecha_inicio:
        proximo_cambio = rotacion.inicio_periodo(cfg, hoy) + timedelta(weeks=cfg.semanas)
    t_hoy = rotacion.turno_efectivo(db, u, hoy)
    h = horarios.horario_de(t_hoy, hoy)
    return {
        "rotacion_activa": rota,
        "hoy": {"entrada": h["entrada"].strftime("%H:%M"), "salida": h["salida"].strftime("%H:%M"),
                "especial": h["especial"]} if h else None,
        "semana_actual": horarios.semana(t_hoy, hoy - timedelta(days=hoy.weekday())),
        "grupo": u.grupo.nombre if u.grupo else None,
        "actual": rotacion._turno_dict(rotacion.turno_efectivo(db, u, hoy)),
        "siguiente_semana": semanas[1] if len(semanas) > 1 else None,
        "proximo_cambio": proximo_cambio,
        "semanas": semanas,
    }
