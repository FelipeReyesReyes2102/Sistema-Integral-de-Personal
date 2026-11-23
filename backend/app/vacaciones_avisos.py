"""Avisos de vacaciones: al jefe y a GH cuando un empleado cancela vacaciones aprobadas, y al empleado (correo y
Teams) cuando sus vacaciones quedan validadas."""
import html
import logging

from sqlalchemy.orm import Session

from . import correo
from .database import SessionLocal
from .incapacidades import gh_de_sede
from .models import NotificacionCorreo, SolicitudVacaciones, Usuario
from .security import ahora

EVENTO_CANCELADAS = "vacaciones_canceladas"
log = logging.getLogger("sip.vacaciones")


def _correo_de(u: Usuario | None) -> str | None:
    return (u.email or u.email_personal) if u else None


def destinatarios(db: Session, s: SolicitudVacaciones) -> list[str]:
    """Jefe que aprobó (o su jefe inmediato) y GH de la sede, sin repetir ni incluir al propio empleado."""
    u = s.usuario
    personas = [s.aprobado_jefe or s.aprobador or (u.jefe if u else None)] + gh_de_sede(db, u.sede_id if u else None)
    vistos, res = set(), []
    for p in personas:
        c = _correo_de(p)
        if c and p.id != s.usuario_id and c.lower() not in vistos:
            vistos.add(c.lower())
            res.append(c)
    return res


def mensaje(s: SolicitudVacaciones) -> tuple[str, str, str]:
    u = s.usuario
    dias = f"{s.horas:g} h" if s.por_horas else f"{s.dias_habiles} día(s)"
    cuando = f"{s.fecha_inicio:%d/%m/%Y} al {s.fecha_fin:%d/%m/%Y} ({dias})"
    titulo = "VACACIONES CANCELADAS POR EL EMPLEADO"
    asunto = f"[SIP-O] Vacaciones canceladas · {u.nombre} · {cuando}"
    filas = [("Empleado", u.nombre), ("No. de nómina", u.numero_empleado), ("Departamento", u.departamento or ""),
             ("Fechas", cuando), ("Periodo", s.periodo.nombre if s.periodo else ""),
             ("Aprobó el jefe", s.aprobado_jefe.nombre if s.aprobado_jefe else ""),
             ("Validó", s.revisado_por.nombre if s.revisado_por else "")]
    nota = ("El empleado canceló estas vacaciones que ya estaban aprobadas; se presentará a trabajar esos días. "
            "Los días regresaron a su saldo.")
    html_ = correo._plantilla(titulo, "#c62828", filas, nota, encabezado="SIP-O · VACACIONES")
    texto = f"{titulo}\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, html_, texto


def notificar_cancelacion(solicitud_id: int):
    """Tarea en segundo plano: avisa al jefe y a GH."""
    with SessionLocal() as db:
        s = db.get(SolicitudVacaciones, solicitud_id)
        if not s or not s.usuario:
            return
        dest = destinatarios(db, s)
        if not dest:
            return
        sede = s.usuario.sede
        asunto, html_, texto = mensaje(s)
        notif = NotificacionCorreo(fecha=ahora(), evento=EVENTO_CANCELADAS, vacaciones_id=s.id,
                                   sede_id=sede.id if sede else None, destinatarios=", ".join(dest), asunto=asunto[:255])
        db.add(notif)
        db.commit()
        correo._registrar_y_enviar(db, notif, correo.config_sede(db, sede), html_, texto)


# ---------------- Vacaciones validadas: aviso al empleado ----------------
EVENTO_VALIDADAS = "vacaciones_validadas"


def _cuando(s: SolicitudVacaciones) -> str:
    dias = f"{s.horas:g} h" if s.por_horas else f"{s.dias_habiles} día(s)"
    return f"{s.fecha_inicio:%d/%m/%Y} al {s.fecha_fin:%d/%m/%Y} ({dias})"


def mensaje_validadas(s: SolicitudVacaciones) -> tuple[str, str, str]:
    u = s.usuario
    titulo = "TUS VACACIONES FUERON VALIDADAS"
    asunto = f"[SIP-O] Vacaciones validadas · {_cuando(s)}"
    filas = [("Empleado", u.nombre), ("Fechas", _cuando(s)), ("Periodo", s.periodo.nombre if s.periodo else ""),
             ("Aprobó el jefe", s.aprobado_jefe.nombre if s.aprobado_jefe else ""),
             ("Validó", s.revisado_por.nombre if s.revisado_por else "")]
    nota = ("Tus vacaciones quedaron autorizadas y los días ya se descontaron de tu saldo. "
            "Puedes consultarlas en SIP-O, en Mis vacaciones.")
    html_ = correo._plantilla(titulo, "#2e7d32", filas, nota, encabezado="SIP-O · VACACIONES")
    texto = f"{titulo}\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, html_, texto


def mensaje_teams_validadas(s: SolicitudVacaciones) -> tuple[str, str, str]:
    """Título, mensaje HTML y texto para el chat de Teams."""
    titulo = "Tus vacaciones fueron validadas"
    datos = [("Fechas", _cuando(s))]
    if s.periodo:
        datos.append(("Periodo", s.periodo.nombre))
    if s.revisado_por:
        datos.append(("Validó", s.revisado_por.nombre))
    cuerpo = (f"<p><b>{titulo}</b></p><p>" + "<br>".join(f"<b>{k}:</b> {html.escape(v)}" for k, v in datos)
              + "</p><p>Los días ya se descontaron de tu saldo. Puedes consultarlas en SIP-O.</p>")
    texto = f"{titulo}\n" + "\n".join(f"{k}: {v}" for k, v in datos)
    return titulo, cuerpo, texto


def notificar_validacion(solicitud_id: int):
    """Avisa al empleado por correo y por Teams que sus vacaciones quedaron validadas. Nunca lanza errores."""
    try:
        with SessionLocal() as db:
            s = db.get(SolicitudVacaciones, solicitud_id)
            if not s or not s.usuario:
                return
            para = _correo_de(s.usuario)
            if not para:
                return
            sede = s.usuario.sede
            asunto, html_, texto = mensaje_validadas(s)
            notif = NotificacionCorreo(fecha=ahora(), evento=EVENTO_VALIDADAS, vacaciones_id=s.id,
                                       sede_id=sede.id if sede else None, destinatarios=para, asunto=asunto[:255])
            db.add(notif)
            db.commit()
            correo._registrar_y_enviar(db, notif, correo.config_sede(db, sede), html_, texto)
            from . import aprobacion_flujo
            error = aprobacion_flujo.enviar_aviso(db, s.usuario.sede_id, para, *mensaje_teams_validadas(s))
            if error and error != aprobacion_flujo.SIN_FLUJO_AVISOS:
                log.warning("Aviso de Teams de las vacaciones %s no enviado: %s", s.id, error)
    except Exception:  # noqa: BLE001 - el aviso nunca debe romper la validación
        log.exception("Error al avisar la validación de las vacaciones %s", solicitud_id)
