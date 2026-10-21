"""Caseta: permisos validados del día y registro de retardos.

- Los usuarios de caseta (y GH) ven los permisos validados del día de su sede: quién sale, entra tarde o sale y regresa,
  y quién está fuera todo el día (home office u otros permisos por días).
- Registran los retardos como solicitud de acceso a planta: se crea un permiso de llegada tarde "Solicitado" que
  autoriza el jefe inmediato en SIP-O o en Teams (lista de SharePoint con aprobación en Teams). Si el empleado no tiene
  jefe, o el jefe no está en planta, se asigna a GH de la sede. Caseta ve la respuesta casi en tiempo real.
"""
import threading
import time as _reloj
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
    ROL_ADMIN, ROLES_ADMIN, EnvioSharePoint, ListaSharePoint, ROLES_SIN_VACACIONES, CANCELADO, ESTADOS_ACTIVOS, ROL_CASETA, SOLICITADO, VALIDADO, NotificacionCorreo, Permiso, Usuario, es_admin,
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


def _teams(db: Session, p: Permiso) -> dict | None:
    """Estado del envío a Teams (lista de SharePoint con aprobación en Teams de la sede), si está configurado."""
    lista = db.scalar(select(ListaSharePoint).where(ListaSharePoint.sede_id == p.usuario.sede_id, ListaSharePoint.tipo == "permisos",
                                                    ListaSharePoint.activo.is_(True), ListaSharePoint.aprobacion_teams.is_(True)))
    if lista is None:
        return None
    env = db.scalar(select(EnvioSharePoint).where(EnvioSharePoint.lista_id == lista.id, EnvioSharePoint.registro_id == p.id))
    if env is None:
        return {"estado": "pendiente", "nota": None}
    return {"estado": "enviado" if env.item_id else env.estado, "nota": env.error or env.decision_nota}


def _fila(db: Session, p: Permiso) -> dict:
    u = p.usuario
    por_dias = tipos_permiso.por_dias(db, u.sede_id, p.tipo)
    return {**_persona(u), "id": p.id, "tipo": p.tipo, "tipo_nombre": tipos_permiso.nombre(db, u.sede_id, p.tipo),
            "categoria": tipos_permiso.categoria(p.tipo), "por_dias": por_dias, "estado": p.estado,
            "fecha": p.fecha.isoformat(), "fecha_fin": (p.fecha_fin or p.fecha).isoformat(),
            "hora_inicio": None if por_dias else p.hora_inicio.strftime("%H:%M"),
            "hora_fin": None if por_dias else p.hora_fin.strftime("%H:%M"), "horas": p.horas,
            "motivo": p.motivo, "autorizo": p.revisado_por.nombre if p.revisado_por else None,
            "aprobador_nombre": p.aprobador.nombre if p.aprobador else None,
            "va_a_gh": p.aprobador is None or (p.aprobador.rol in ROLES_ADMIN and p.aprobador_id != u.jefe_id),
            "registrado_por": p.registrado_por.nombre if p.registrado_por else None,
            "motivo_rechazo": p.motivo_rechazo, "observaciones": p.observaciones,
            "fecha_revision": p.fecha_revision.isoformat() if p.fecha_revision else None,
            "teams": _teams(db, p) if p.registrado_por_id else None}


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
def empleados(q: str | None = None, con_permisos: bool = False, limite: int = 30, db: Session = Depends(get_db),
              user: Usuario = Depends(require_caseta)):
    """Buscador de empleados de la sede (sin acentos, por palabras, nombre/nómina/puesto/departamento/correo).

    Incluye su horario de entrada de hoy y su jefe. Con `con_permisos` agrega sus permisos del día (validados y
    pendientes) para la pestaña "Permisos de hoy"; ahí también puede buscarse uno mismo."""
    dia = ahora_en(user.sede).date()
    res = []
    for u in buscar_usuarios(db, _sedes(db, user), q, excluir_id=None if con_permisos else user.id, limite=max(limite, 1) * 2):
        if u.rol in ROLES_SIN_VACACIONES:  # médico y caseta no tienen permisos en el sistema
            continue
        h = horarios.horario_de(u.turno, dia)
        fila = {**_persona(u), "id": u.id, "entrada_hoy": h["entrada"].strftime("%H:%M") if h else None,
                "salida_hoy": h["salida"].strftime("%H:%M") if h else None, "jefe_nombre": u.jefe.nombre if u.jefe else None}
        if con_permisos:
            q_p = select(Permiso).where(Permiso.usuario_id == u.id, Permiso.estado.in_((SOLICITADO, VALIDADO)),
                                        Permiso.fecha <= dia, func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= dia)
            fila["permisos_hoy"] = [_fila(db, p) for p in db.scalars(q_p.order_by(Permiso.hora_inicio))]
        res.append(fila)
        if len(res) >= limite:
            break
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
    destino = "GH" if p.aprobador_id is None else "tu autorización"
    asunto = f"[SIP-O] Acceso a planta por retardo · {u.nombre} · {p.fecha:%d/%m/%Y} {p.hora_fin:%H:%M}"
    filas = [("Empleado", u.nombre), ("No. de nómina", u.numero_empleado), ("Departamento", u.departamento or ""),
             ("Fecha", f"{p.fecha:%d/%m/%Y}"), ("Hora de entrada", f"{p.hora_inicio:%H:%M}"),
             ("Hora de llegada", f"{p.hora_fin:%H:%M} ({p.horas:g} h de retardo)"), ("Motivo", p.motivo or ""),
             ("Registró en caseta", p.registrado_por.nombre if p.registrado_por else "")]
    nota = (f"La persona está en caseta esperando acceso a planta. Queda como permiso de llegada tarde pendiente de {destino}: "
            "autorízalo o recházalo en Teams o en SIP-O → Por aprobar → Permisos. Caseta ve tu respuesta al momento.")
    html_ = correo._plantilla("ACCESO A PLANTA POR RETARDO", "#a35d00", filas, nota, encabezado="SIP-O · CASETA")
    texto = "ACCESO A PLANTA POR RETARDO\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
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
    if emp.rol in ROLES_SIN_VACACIONES:
        raise HTTPException(422, "Al médico de planta y al personal de caseta no se les registran retardos en el sistema.")
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
    aprobador = _gh_aprobador(db, emp) if a_gh else jefe
    motivo = (data.motivo or "").strip()
    texto = (f"Acceso a planta por retardo (llegó {data.hora_llegada:%H:%M}, entrada {entrada:%H:%M}). "
             f"Registrado en caseta por {user.nombre}." + (f" Motivo: {motivo}" if motivo else ""))
    p = Permiso(usuario_id=emp.id, tipo=TIPO_RETARDO, fecha=dia, hora_inicio=entrada, hora_fin=data.hora_llegada,
                horas=reglas.horas_permiso(entrada, data.hora_llegada), motivo=texto, departamento=emp.departamento,
                aprobador_id=aprobador.id if aprobador else None, estado=SOLICITADO, registrado_por_id=user.id)
    db.add(p)
    db.flush()
    auditar(db, "retardo_registrado", usuario_id=emp.id, actor_id=user.id,
            detalle=f"permiso {p.id} · {dia:%d/%m/%Y} entrada {entrada:%H:%M} llegada {data.hora_llegada:%H:%M}"
                    f" · {'GH' if a_gh else 'jefe'} {aprobador.nombre if aprobador else ''}".rstrip())
    db.commit()
    tareas.add_task(notificar_retardo, p.id)
    return _fila(db, p)


def _gh_aprobador(db: Session, emp: Usuario) -> Usuario | None:
    """GH de la sede que recibe el retardo (en la app y en Teams) cuando no hay jefe o no está en planta."""
    candidatos = [u for u in gh_de_sede(db, emp.sede_id) if _correo_de(u) and u.id != emp.id]
    candidatos.sort(key=lambda u: (u.rol != ROL_ADMIN, u.nombre))
    return candidatos[0] if candidatos else None


_ultima_revision = [0.0]
_candado_revision = threading.Lock()


def _revisar_teams_pronto():
    """Lee las decisiones de Teams al momento (como máximo cada 15 s) para que caseta vea la respuesta del jefe."""
    if _reloj.monotonic() - _ultima_revision[0] < 15 or not _candado_revision.acquire(blocking=False):
        return
    try:
        _ultima_revision[0] = _reloj.monotonic()
        from .. import sharepoint
        sharepoint.revisar_decisiones()
    except Exception:  # noqa: BLE001 - nunca debe impedir mostrar la lista
        import logging
        logging.getLogger("sip.caseta").warning("No se pudieron revisar las decisiones de Teams", exc_info=True)
    finally:
        _candado_revision.release()


@router.get("/retardos")
def retardos(fecha: date | None = None, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Retardos registrados en caseta en el día, con su estado (esperando, autorizado o denegado)."""
    dia = fecha or ahora_en(user.sede).date()
    esperando = db.scalar(select(func.count(Permiso.id)).where(Permiso.registrado_por_id.is_not(None), Permiso.fecha == dia,
                                                                 Permiso.estado == SOLICITADO)) or 0
    if esperando:
        _revisar_teams_pronto()
        db.expire_all()
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

