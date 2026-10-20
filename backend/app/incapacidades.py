"""Incapacidades: se generan en una consulta médica, las valida el jefe del empleado y se notifican a GH.

- El médico (o el usuario con permiso de registrar consultas) la captura en la consulta.
- Queda "solicitada" para el jefe directo del empleado (si no tiene jefe, la valida GH) y se le avisa por correo.
- Al validarla o rechazarla se notifica por correo a GH de la sede del empleado.
- El jefe y GH ven fechas, días, tipo, folio y observaciones; nunca síntomas, diagnóstico ni medicamentos.
"""
import logging
from datetime import date

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import correo
from .database import SessionLocal
from .models import (
    RECHAZADO, ROL_ADMIN, ROL_GERENCIA_GH, SOLICITADO, VALIDADO, AdminSede, ConsultaMedica, Incapacidad,
    NotificacionCorreo, Usuario, es_medico,
)
from .schemas import IncapacidadIn, IncapacidadOut
from .security import ahora
from .sedes import admin_permite

log = logging.getLogger(__name__)

TIPOS = {"enfermedad_general": "Enfermedad general", "riesgo_trabajo": "Riesgo de trabajo", "maternidad": "Maternidad",
         "otro": "Otro"}
MAX_DIAS = 365


def out(i: Incapacidad) -> IncapacidadOut:
    o = IncapacidadOut.model_validate(i)
    o.usuario_nombre = i.usuario.nombre if i.usuario else None
    o.usuario_numero = i.usuario.numero_empleado if i.usuario else None
    o.usuario_departamento = i.usuario.departamento if i.usuario else None
    o.medico_nombre = i.medico.nombre if i.medico else None
    o.aprobador_nombre = i.aprobador.nombre if i.aprobador else None
    o.revisado_por_nombre = i.revisado_por.nombre if i.revisado_por else None
    return o


def puede_ver(user: Usuario, i: Incapacidad) -> bool:
    sede = i.usuario.sede_id if i.usuario else None
    return (i.usuario_id == user.id or i.aprobador_id == user.id or (i.usuario and i.usuario.jefe_id == user.id)
            or admin_permite(user, sede) or (es_medico(user) and user.sede_id == sede))


def puede_validar(user: Usuario, i: Incapacidad) -> bool:
    if i.usuario_id == user.id:
        return False
    return i.aprobador_id == user.id or admin_permite(user, i.usuario.sede_id if i.usuario else None)


def aplicar(db: Session, c: ConsultaMedica, data: IncapacidadIn | None, paciente: Usuario, medico: Usuario) -> bool:
    """Crea, actualiza o quita la incapacidad de la consulta. Devuelve True si hay que avisar al jefe."""
    actual = c.incapacidad
    if data is None:
        if actual is not None:
            if actual.estado != SOLICITADO:
                raise HTTPException(400, "La incapacidad ya fue revisada por el jefe; no se puede quitar de la consulta.")
            c.incapacidad = None
        return False
    if data.fecha_fin < data.fecha_inicio:
        raise HTTPException(422, "La fecha final de la incapacidad no puede ser anterior a la inicial.")
    dias = (data.fecha_fin - data.fecha_inicio).days + 1
    if dias > MAX_DIAS:
        raise HTTPException(422, f"La incapacidad puede ser por máximo {MAX_DIAS} días.")
    valores = {"fecha_inicio": data.fecha_inicio, "fecha_fin": data.fecha_fin, "dias": dias, "tipo": data.tipo,
               "folio": (data.folio or "").strip() or None, "observaciones": (data.observaciones or "").strip() or None}
    if actual is not None:
        if actual.estado != SOLICITADO:
            if any(getattr(actual, k) != v for k, v in valores.items()):
                raise HTTPException(400, "La incapacidad ya fue revisada por el jefe; ya no se puede modificar.")
            return False
        for k, v in valores.items():
            setattr(actual, k, v)
        actual.usuario_id = paciente.id
        actual.aprobador_id = paciente.jefe_id if paciente.jefe_id != paciente.id else None
        return False
    c.incapacidad = Incapacidad(usuario_id=paciente.id, medico_id=medico.id, estado=SOLICITADO,
                                aprobador_id=paciente.jefe_id if paciente.jefe_id != paciente.id else None, **valores)
    return True


def revisar(db: Session, i: Incapacidad, actor: Usuario, validar: bool, motivo: str | None = None):
    if i.estado != SOLICITADO:
        raise HTTPException(400, "La incapacidad ya fue revisada.")
    if not puede_validar(actor, i):
        raise HTTPException(403, "Solo el jefe del empleado o GH pueden validar la incapacidad.")
    if not validar and not (motivo or "").strip():
        raise HTTPException(422, "Indica el motivo del rechazo.")
    i.estado = VALIDADO if validar else RECHAZADO
    i.motivo_rechazo = None if validar else motivo.strip()
    i.revisado_por_id, i.fecha_revision = actor.id, ahora()


# ---------------- Correos ----------------
def _correo_de(u: Usuario | None) -> str | None:
    return (u.email or u.email_personal) if u else None


def gh_de_sede(db: Session, sede_id: int | None) -> list[Usuario]:
    """GH de la sede y Gerencia GH que la tiene asignada."""
    asignados = select(AdminSede.usuario_id).where(AdminSede.sede_id == sede_id)
    q = select(Usuario).where(Usuario.activo.is_(True), or_(
        (Usuario.rol.in_((ROL_ADMIN, ROL_GERENCIA_GH))) & (Usuario.sede_id == sede_id),
        (Usuario.rol == ROL_GERENCIA_GH) & Usuario.id.in_(asignados)))
    return list(db.scalars(q))


def _fmt(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def mensaje(i: Incapacidad, evento: str) -> tuple[str, str, str]:
    u = i.usuario
    tipo = TIPOS.get(i.tipo, i.tipo)
    cuando = f"{_fmt(i.fecha_inicio)} al {_fmt(i.fecha_fin)} ({i.dias} día(s))"
    if evento == "incapacidad_solicitada":
        titulo, color = "INCAPACIDAD POR VALIDAR", "#a35d00"
        asunto = f"[SIP-O] Incapacidad por validar · {u.nombre} · {cuando}"
        nota = "Entra a SIP-O → Por aprobar → Incapacidades para validarla o rechazarla."
    elif evento == "incapacidad_validada":
        titulo, color = "INCAPACIDAD VALIDADA", "#2e7d32"
        asunto = f"[SIP-O] Incapacidad validada · {u.nombre} · {cuando}"
        nota = "El jefe validó la incapacidad. Puedes consultarla en SIP-O → Todas las solicitudes → Incapacidades."
    else:
        titulo, color = "INCAPACIDAD RECHAZADA", "#c62828"
        asunto = f"[SIP-O] Incapacidad rechazada · {u.nombre} · {cuando}"
        nota = f"Motivo del rechazo: {i.motivo_rechazo or '—'}"
    filas = [("Empleado", u.nombre), ("No. de nómina", u.numero_empleado), ("Departamento", u.departamento or ""),
             ("Tipo", tipo), ("Fechas", cuando), ("Folio", i.folio or ""), ("Observaciones", i.observaciones or ""),
             ("Registró", i.medico.nombre if i.medico else ""),
             ("Revisó", i.revisado_por.nombre if i.revisado_por else "")]
    html_ = correo._plantilla(titulo, color, filas, nota, encabezado="SIP-O · INCAPACIDADES")
    texto = f"{titulo}\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, html_, texto


def destinatarios(db: Session, i: Incapacidad, evento: str) -> list[str]:
    if evento == "incapacidad_solicitada" and i.aprobador is not None:
        personas = [i.aprobador]
    else:  # sin jefe la valida GH; al validarse o rechazarse se avisa a GH
        personas = gh_de_sede(db, i.usuario.sede_id if i.usuario else None)
    vistos, res = set(), []
    for p in personas:
        c = _correo_de(p)
        if c and c.lower() not in vistos and p.id != (i.revisado_por_id if evento != "incapacidad_solicitada" else None):
            vistos.add(c.lower())
            res.append(c)
    return res


def notificar(incapacidad_id: int, evento: str):
    """Tarea en segundo plano: avisa al jefe (solicitada) o a GH (validada / rechazada)."""
    with SessionLocal() as db:
        i = db.get(Incapacidad, incapacidad_id)
        if not i or not i.usuario:
            return
        dest = destinatarios(db, i, evento)
        if not dest:
            return
        sede = i.usuario.sede
        asunto, html_, texto = mensaje(i, evento)
        notif = NotificacionCorreo(fecha=ahora(), evento=evento, incapacidad_id=i.id, sede_id=sede.id if sede else None,
                                   destinatarios=", ".join(dest), asunto=asunto[:255])
        db.add(notif)
        db.commit()
        correo._registrar_y_enviar(db, notif, correo.config_sede(db, sede), html_, texto)

