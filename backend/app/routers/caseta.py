"""Caseta: permisos validados del día y registro de retardos.

- Los usuarios de caseta (y GH) ven los permisos validados del día de su sede: quién sale, entra tarde o sale y regresa,
  y quién está fuera todo el día (home office u otros permisos por días).
- Registran los retardos: se crea un permiso de llegada tarde "Solicitado" que valida el jefe inmediato del empleado.
  Si el empleado no tiene jefe, o el jefe no está en planta, se envía a GH.
"""
from datetime import date, time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import correo, horarios, reglas, tipos_permiso
from ..busqueda import buscar_usuarios
from ..database import SessionLocal, get_db
from ..incapacidades import gh_de_sede
from ..models import (
    CANCELADO, ESTADOS_ACTIVOS, ROL_CASETA, SOLICITADO, VALIDADO, NotificacionCorreo, Permiso, Usuario, es_admin,
)
from ..security import ahora, auditar, get_current_user
from ..sedes import ahora_en, sedes_visibles

router = APIRouter(prefix="/api/caseta", tags=["caseta"])
TIPO_RETARDO = "llegada_tarde"


def require_caseta(user: Usuario = Depends(get_current_user)) -> Usuario:
    if user.rol != ROL_CASETA and not es_admin(user):
        raise HTTPException(403, "Solo el personal de caseta y GH pueden usar este apartado.")
    return user


def _sedes(db: Session, user: Usuario) -> set[int | None]:
    return {s.id for s in sedes_visibles(db, user)} | {user.sede_id} if es_admin(user) else {user.sede_id}


def _persona(u: Usuario) -> dict:
    return {"usuario_id": u.id, "nombre": u.nombre, "numero_empleado": u.numero_empleado, "puesto": u.puesto,
            "departamento": u.departamento, "tiene_foto": u.foto_tipo is not None, "rol": u.rol,
            "turno": u.turno.nombre if u.turno else None, "sede_nombre": u.sede.nombre if u.sede else None}


def _fila(db: Session, p: Permiso) -> dict:
    u = p.usuario
    por_dias = tipos_permiso.por_dias(db, u.sede_id, p.tipo)
    return {**_persona(u), "id": p.id, "tipo": p.tipo, "tipo_nombre": tipos_permiso.nombre(db, u.sede_id, p.tipo),
            "categoria": tipos_permiso.categoria(p.tipo), "por_dias": por_dias, "estado": p.estado,
            "fecha": p.fecha.isoformat(), "fecha_fin": (p.fecha_fin or p.fecha).isoformat(),
            "hora_inicio": None if por_dias else p.hora_inicio.strftime("%H:%M"),
            "hora_fin": None if por_dias else p.hora_fin.strftime("%H:%M"), "horas": p.horas,
            "motivo": p.motivo, "autorizo": p.revisado_por.nombre if p.revisado_por else None,
            "aprobador_nombre": p.aprobador.nombre if p.aprobador else None, "va_a_gh": p.aprobador_id is None,
            "registrado_por": p.registrado_por.nombre if p.registrado_por else None,
            "motivo_rechazo": p.motivo_rechazo}


@router.get("/hoy")
def hoy(fecha: date | None = None, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Permisos validados del día en la sede: por horas (con su horario) y por días (fuera de planta todo el día)."""
    dia = fecha or ahora_en(user.sede).date()
    usuarios = select(Usuario.id).where(Usuario.sede_id.in_([x for x in _sedes(db, user) if x is not None] or [-1]))
    q = select(Permiso).where(Permiso.estado == VALIDADO, Permiso.usuario_id.in_(usuarios), Permiso.fecha <= dia,
                              func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= dia)
    filas = [_fila(db, p) for p in db.scalars(q)]
    por_horas = sorted([f for f in filas if not f["por_dias"]], key=lambda f: (f["hora_inicio"] or "", f["nombre"]))
    por_dias = sorted([f for f in filas if f["por_dias"]], key=lambda f: f["nombre"])
    return {"fecha": dia.isoformat(), "hora_local": ahora_en(user.sede).strftime("%H:%M"),
            "por_horas": por_horas, "por_dias": por_dias}


@router.get("/empleados")
def empleados(q: str | None = None, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Buscador de empleados de la sede para registrar un retardo; incluye su horario de entrada de hoy."""
    dia = ahora_en(user.sede).date()
    res = []
    for u in buscar_usuarios(db, _sedes(db, user), q, excluir_id=user.id, limite=30):
        h = horarios.horario_de(u.turno, dia)
        res.append({**_persona(u), "id": u.id, "entrada_hoy": h["entrada"].strftime("%H:%M") if h else None,
                    "jefe_nombre": u.jefe.nombre if u.jefe else None})
    return res


class RetardoIn(BaseModel):
    usuario_id: int
    hora_llegada: time
    motivo: str | None = Field(None, max_length=500)
    enviar_gh: bool = False    # el jefe inmediato no está en planta: lo valida GH


def _correo_de(u: Usuario | None) -> str | None:
    return (u.email or u.email_personal) if u else None


def mensaje_retardo(p: Permiso) -> tuple[str, str, str]:
    u = p.usuario
    destino = "GH" if p.aprobador_id is None else "tu validación"
    asunto = f"[SIP-O] Retardo por validar · {u.nombre} · {p.fecha:%d/%m/%Y} {p.hora_fin:%H:%M}"
    filas = [("Empleado", u.nombre), ("No. de nómina", u.numero_empleado), ("Departamento", u.departamento or ""),
             ("Fecha", f"{p.fecha:%d/%m/%Y}"), ("Hora de entrada", f"{p.hora_inicio:%H:%M}"),
             ("Hora de llegada", f"{p.hora_fin:%H:%M} ({p.horas:g} h de retardo)"), ("Motivo", p.motivo or ""),
             ("Registró en caseta", p.registrado_por.nombre if p.registrado_por else "")]
    nota = (f"Caseta registró un retardo que queda como permiso de llegada tarde pendiente de {destino}. "
            "Entra a SIP-O → Por aprobar (o Todas las solicitudes) → Permisos para validarlo o rechazarlo.")
    html_ = correo._plantilla("RETARDO POR VALIDAR", "#a35d00", filas, nota, encabezado="SIP-O · CASETA")
    texto = "RETARDO POR VALIDAR\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, html_, texto


def destinatarios_retardo(db: Session, p: Permiso) -> list[str]:
    personas = [p.aprobador] if p.aprobador is not None else gh_de_sede(db, p.usuario.sede_id)
    return list(dict.fromkeys(c for c in (_correo_de(x) for x in personas) if c))


def notificar_retardo(permiso_id: int):
    """Avisa por correo al jefe inmediato (o a GH) que hay un retardo por validar."""
    with SessionLocal() as db:
        p = db.get(Permiso, permiso_id)
        if not p or p.estado != SOLICITADO:
            return
        dest = destinatarios_retardo(db, p)
        if not dest:
            return
        sede = p.usuario.sede
        asunto, html_, texto = mensaje_retardo(p)
        notif = NotificacionCorreo(fecha=ahora(), evento="retardo_registrado", permiso_id=p.id,
                                   sede_id=sede.id if sede else None, destinatarios=", ".join(dest), asunto=asunto[:255])
        db.add(notif)
        db.commit()
        correo._registrar_y_enviar(db, notif, correo.config_sede(db, sede), html_, texto)


@router.post("/retardos", status_code=201)
def registrar_retardo(data: RetardoIn, tareas: BackgroundTasks, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_caseta)):
    emp = db.get(Usuario, data.usuario_id)
    if not emp or not emp.activo or emp.sede_id not in _sedes(db, user):
        raise HTTPException(404, "Empleado no encontrado en tu sede.")
    if emp.id == user.id:
        raise HTTPException(422, "No puedes registrar tu propio retardo.")
    dia = ahora_en(emp.sede).date()
    h = horarios.horario_de(emp.turno, dia)
    if not h:
        raise HTTPException(422, f"{emp.nombre} no tiene turno asignado: no se puede calcular el retardo. Pide a GH que le asigne uno.")
    entrada = h["entrada"]
    if data.hora_llegada <= entrada:
        raise HTTPException(422, f"La hora de llegada ({data.hora_llegada:%H:%M}) no es posterior a su entrada de hoy ({entrada:%H:%M}).")
    duplicado = db.scalar(select(Permiso.id).where(
        Permiso.usuario_id == emp.id, Permiso.tipo == TIPO_RETARDO, Permiso.fecha == dia,
        Permiso.estado.in_(ESTADOS_ACTIVOS)).limit(1))
    if duplicado:
        raise HTTPException(409, f"{emp.nombre} ya tiene un permiso de llegada tarde hoy.")
    jefe = emp.jefe if emp.jefe and emp.jefe.activo and emp.jefe_id != emp.id else None
    a_gh = data.enviar_gh or jefe is None
    p = Permiso(usuario_id=emp.id, tipo=TIPO_RETARDO, fecha=dia, hora_inicio=entrada, hora_fin=data.hora_llegada,
                horas=reglas.horas_permiso(entrada, data.hora_llegada),
                motivo=(data.motivo or "").strip() or "Retardo registrado en caseta", departamento=emp.departamento,
                aprobador_id=None if a_gh else jefe.id, estado=SOLICITADO, registrado_por_id=user.id)
    db.add(p)
    db.flush()
    auditar(db, "retardo_registrado", usuario_id=emp.id, actor_id=user.id,
            detalle=f"permiso {p.id} · {dia:%d/%m/%Y} entrada {entrada:%H:%M} llegada {data.hora_llegada:%H:%M}"
                    f" · {'GH' if a_gh else 'jefe ' + jefe.nombre}")
    db.commit()
    tareas.add_task(notificar_retardo, p.id)
    return _fila(db, p)


@router.get("/retardos")
def retardos(fecha: date | None = None, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Retardos registrados en caseta en el día, con su estado (pendiente, validado o rechazado)."""
    dia = fecha or ahora_en(user.sede).date()
    usuarios = select(Usuario.id).where(Usuario.sede_id.in_([x for x in _sedes(db, user) if x is not None] or [-1]))
    q = (select(Permiso).where(Permiso.registrado_por_id.is_not(None), Permiso.fecha == dia, Permiso.usuario_id.in_(usuarios))
         .order_by(Permiso.hora_fin.desc()))
    return [_fila(db, p) for p in db.scalars(q)]


@router.post("/retardos/{pid}/cancelar")
def cancelar_retardo(pid: int, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Caseta corrige un retardo mal registrado mientras sigue pendiente."""
    p = db.get(Permiso, pid)
    if not p or p.registrado_por_id is None or p.usuario.sede_id not in _sedes(db, user):
        raise HTTPException(404, "Retardo no encontrado")
    if p.estado != SOLICITADO:
        raise HTTPException(400, "Solo se cancelan retardos pendientes; uno ya revisado lo cancela el jefe o GH.")
    p.estado = CANCELADO
    auditar(db, "retardo_cancelado", usuario_id=p.usuario_id, actor_id=user.id, detalle=f"permiso {p.id}")
    db.commit()
    return _fila(db, p)

