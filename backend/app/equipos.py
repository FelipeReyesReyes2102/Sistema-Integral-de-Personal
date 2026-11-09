"""Salida de equipos de cómputo (formato F-630-03 "Entrada y salida de equipos de cómputo").

1. El empleado la solicita con los datos del equipo y su firma.
2. Su jefe directo la autoriza o la rechaza (en SIP-O o en Teams, si la sede lo activó).
3. TI la revisa: puede sellarla (autorizar) o rechazarla en cualquier momento antes de que el equipo salga.
   Si la rechaza se avisa por correo al empleado y a su jefe.
4. Caseta hace la revisión de seguridad: ve las salidas autorizadas del día y registra la salida y el regreso.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import correo
from .database import SessionLocal
from .models import (
    BORRADOR, CANCELADO, RECHAZADO, SOLICITADO, VALIDADO, NotificacionCorreo, SalidaEquipo, Usuario, es_admin,
)
from .schemas import SalidaEquipoOut
from .security import ahora
from .sedes import admin_permite, hoy_de

TIPOS = {"laptop": "Laptop", "escritorio": "De escritorio"}


# Función apagada: la salida de equipo se pide como un permiso común («Salida de equipo»). Las salidas que ya existen
# se conservan en la base. Para reactivarla, poner True (y SALIDAS_EQUIPO en frontend/src/utils.js).
HABILITADO = False
MENSAJE_DESHABILITADO = "La salida de equipo ahora se pide como un permiso: elige «Salida de equipo» en Solicitar permiso."


def situacion(s: SalidaEquipo) -> str:
    if s.regreso_registrado:
        return "Regresó a planta"
    if s.salida_registrada:
        return "Fuera de planta"
    if s.estado == RECHAZADO:
        return "Rechazada por TI" if s.ti_estado == "rechazado" else "Rechazada por el jefe"
    if s.estado == VALIDADO:
        return "Autorizada por el jefe y TI" if s.ti_estado == "autorizado" else "Autorizada por el jefe"
    return {BORRADOR: "Borrador", SOLICITADO: "Esperando al jefe", CANCELADO: "Cancelada"}.get(s.estado, s.estado)


def puede_salir(s: SalidaEquipo) -> bool:
    """Autorizada por el jefe, sin rechazo de TI, aún no sale y hoy está dentro del plazo."""
    hoy = hoy_de(s.usuario)
    return (s.estado == VALIDADO and s.ti_estado != "rechazado" and s.salida_registrada is None
            and s.fecha_inicio <= hoy <= s.fecha_fin)


def out(s: SalidaEquipo) -> SalidaEquipoOut:
    o = SalidaEquipoOut.model_validate(s)
    u = s.usuario
    o.usuario_nombre = u.nombre if u else None
    o.usuario_numero = u.numero_empleado if u else None
    o.usuario_departamento = u.departamento if u else None
    o.usuario_puesto = u.puesto if u else None
    o.tiene_foto = bool(u and u.foto_tipo)
    o.aprobador_nombre = s.aprobador.nombre if s.aprobador else None
    o.revisado_por_nombre = s.revisado_por.nombre if s.revisado_por else None
    o.ti_por_nombre = s.ti_por.nombre if s.ti_por else None
    o.salida_por_nombre = s.salida_por.nombre if s.salida_por else None
    o.regreso_por_nombre = s.regreso_por.nombre if s.regreso_por else None
    o.tiene_firma, o.tiene_firma_ti = bool(s.firma), bool(s.ti_firma)
    o.situacion, o.puede_salir = situacion(s), puede_salir(s)
    return o


def puede_ver(user: Usuario, s: SalidaEquipo) -> bool:
    sede = s.usuario.sede_id if s.usuario else None
    from .services import es_jefe_de
    return (s.usuario_id == user.id or s.aprobador_id == user.id or es_jefe_de(user, s.usuario)
            or admin_permite(user, sede) or ((user.puede_ti or user.rol == "caseta") and user.sede_id == sede))


def puede_revisar_jefe(user: Usuario, s: SalidaEquipo) -> bool:
    if s.usuario_id == user.id:
        return False
    from .services import es_jefe_de
    return s.aprobador_id == user.id or es_jefe_de(user, s.usuario) or admin_permite(user, s.usuario.sede_id if s.usuario else None)


def autorizar_jefe(s: SalidaEquipo, actor: Usuario):
    """Autorización del jefe (desde SIP-O o Teams); después sigue la revisión de TI y la caseta."""
    s.estado, s.revisado_por_id, s.fecha_revision = VALIDADO, actor.id, datetime.now()


def rechazar_jefe(s: SalidaEquipo, actor: Usuario, motivo: str):
    s.estado, s.motivo_rechazo = RECHAZADO, motivo
    s.revisado_por_id, s.fecha_revision = actor.id, datetime.now()


def puede_revisar_ti(user: Usuario, s: SalidaEquipo) -> bool:
    if s.usuario_id == user.id:
        return False
    sede = s.usuario.sede_id if s.usuario else None
    return (user.puede_ti and (user.sede_id == sede or admin_permite(user, sede))) or user.rol == "superadmin"


def exigir(condicion: bool, mensaje: str, codigo: int = 400):
    if not condicion:
        raise HTTPException(codigo, mensaje)


# ---------------- Correos ----------------
def _correo(u: Usuario | None) -> str | None:
    return (u.email or u.email_personal) if u else None


def mensaje(s: SalidaEquipo, evento: str) -> tuple[str, str, str]:
    u = s.usuario
    equipo = f"{TIPOS.get(s.tipo_equipo, s.tipo_equipo)} {s.marca} {s.modelo} · SN {s.serie}"
    plazo = f"{s.fecha_inicio:%d/%m/%Y} al {s.fecha_fin:%d/%m/%Y}"
    if evento == "equipo_solicitado":
        titulo, color = "SALIDA DE EQUIPO POR AUTORIZAR", "#a35d00"
        asunto = f"[SIP-O] Salida de equipo por autorizar · {u.nombre} · {s.serie}"
        nota = "Entra a SIP-O → Por aprobar → Salida de equipo para autorizarla o rechazarla."
    elif evento == "equipo_rechazado_ti":
        titulo, color = "SALIDA DE EQUIPO RECHAZADA POR TI", "#c62828"
        asunto = f"[SIP-O] TI rechazó la salida de equipo · {u.nombre} · {s.serie}"
        nota = f"Motivo de TI: {s.ti_nota or s.motivo_rechazo or '—'}. El equipo no puede salir de planta."
    elif evento == "equipo_rechazado":
        titulo, color = "SALIDA DE EQUIPO RECHAZADA", "#c62828"
        asunto = f"[SIP-O] Tu jefe rechazó la salida de equipo · {s.serie}"
        nota = f"Motivo: {s.motivo_rechazo or '—'}."
    else:
        titulo, color = "SALIDA DE EQUIPO AUTORIZADA", "#2e7d32"
        asunto = f"[SIP-O] Salida de equipo autorizada · {s.serie}"
        nota = "Tu jefe autorizó la salida. Preséntate en caseta con el equipo dentro del plazo; TI puede revisarla antes."
    filas = [("Empleado", u.nombre), ("No. de nómina", u.numero_empleado), ("Departamento", u.departamento or ""),
             ("Equipo", equipo), ("Accesorios", s.accesorios or ""), ("Plazo", plazo), ("Justificación", s.justificacion),
             ("Jefe", s.aprobador.nombre if s.aprobador else ""),
             ("Revisó TI", s.ti_por.nombre if s.ti_por else "")]
    html_ = correo._plantilla(titulo, color, filas, nota, encabezado="SIP-O · SALIDA DE EQUIPO DE CÓMPUTO (F-630-03)")
    texto = f"{titulo}\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, html_, texto


def destinatarios(s: SalidaEquipo, evento: str) -> list[str]:
    if evento == "equipo_solicitado":
        personas = [s.aprobador]
    elif evento == "equipo_rechazado_ti":
        personas = [s.usuario, s.aprobador or (s.usuario.jefe if s.usuario else None)]
    else:
        personas = [s.usuario]
    return list(dict.fromkeys(c for c in (_correo(p) for p in personas) if c))


def notificar(salida_id: int, evento: str):
    """Tarea en segundo plano: avisa por correo según el evento (nunca impide la operación)."""
    with SessionLocal() as db:
        s = db.get(SalidaEquipo, salida_id)
        if not s or not s.usuario:
            return
        dest = destinatarios(s, evento)
        if not dest:
            return
        sede = s.usuario.sede
        asunto, html_, texto = mensaje(s, evento)
        notif = NotificacionCorreo(fecha=ahora(), evento=evento, salida_equipo_id=s.id, sede_id=sede.id if sede else None,
                                   destinatarios=", ".join(dest), asunto=asunto[:255])
        db.add(notif)
        db.commit()
        correo._registrar_y_enviar(db, notif, correo.config_sede(db, sede), html_, texto)


def obtener(db: Session, sid: int, user: Usuario) -> SalidaEquipo:
    s = db.get(SalidaEquipo, sid)
    if not s or not puede_ver(user, s):
        raise HTTPException(404, "Solicitud de salida de equipo no encontrada")
    return s

