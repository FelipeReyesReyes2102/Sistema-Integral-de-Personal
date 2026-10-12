"""Envío de correos y avisos a caseta.

- La configuración se guarda en la tabla `configuracion` (claves CORREO_*); la contraseña SMTP va cifrada.
- Métodos: SMTP (cualquier servidor) o Microsoft 365 vía Graph (permiso de aplicación Mail.Send).
- Cada envío queda en `notificaciones_correo` (enviado / error) y puede reintentarse.
"""
import html
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import httpx
from sqlalchemy.orm import Session

from . import microsoft
from .config import settings
from .config_dinamica import cifrar, descifrar
from .database import SessionLocal
from .models import (
    PERMISO_HOME_OFFICE, ConfiguracionApp, NotificacionCorreo, Permiso,
)
from .security import ahora

log = logging.getLogger("sip.correo")

EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
TIPOS_AVISO_DEFECTO = ["llegada_tarde", "salida_temprana", "salida_intermedia"]
NOMBRES_TIPO = {
    "llegada_tarde": "Llegada tarde",
    "salida_temprana": "Salida temprana",
    "salida_intermedia": "Salida durante la jornada",
    "home_office": "Home office",
    "consulta_medica": "Consulta médica",
}

# clave -> (valor por defecto, ¿secreto?)
CLAVES = {
    "CORREO_CASETA_ACTIVO": ("false", False),
    "CORREO_CASETA_DESTINATARIOS": ("", False),
    "CORREO_CASETA_TIPOS": (",".join(TIPOS_AVISO_DEFECTO), False),
    "CORREO_METODO": ("smtp", False),           # smtp | graph
    "CORREO_REMITENTE": ("", False),
    "CORREO_REMITENTE_NOMBRE": ("SIP-O Sistema Integral de Personal", False),
    "CORREO_SMTP_HOST": ("", False),
    "CORREO_SMTP_PUERTO": ("587", False),
    "CORREO_SMTP_SEGURIDAD": ("starttls", False),  # starttls | ssl | ninguna
    "CORREO_SMTP_USUARIO": ("", False),
    "CORREO_SMTP_PASSWORD": ("", True),
}


class ErrorCorreo(Exception):
    pass


def lista_correos(texto: str) -> list[str]:
    return [c.strip().lower() for c in re.split(r"[,;\s]+", texto or "") if c.strip()]


def cargar(db: Session) -> dict:
    """Configuración efectiva de correo (con la contraseña descifrada; no se devuelve al navegador)."""
    filas = {f.clave: f for f in db.query(ConfiguracionApp).filter(ConfiguracionApp.clave.in_(list(CLAVES)))}
    cfg = {}
    for clave, (defecto, secreto) in CLAVES.items():
        f = filas.get(clave)
        valor = f.valor if f and f.valor is not None else defecto
        if f and f.cifrado and f.valor:
            valor = descifrar(f.valor) or ""
        cfg[clave] = valor
    return cfg


def guardar(db: Session, cambios: dict[str, str | None], actor_id: int | None):
    for clave, valor in cambios.items():
        if clave not in CLAVES:
            continue
        secreto = CLAVES[clave][1]
        fila = db.get(ConfiguracionApp, clave)
        if valor is None:
            if fila:
                db.delete(fila)
            continue
        if fila is None:
            fila = ConfiguracionApp(clave=clave)
            db.add(fila)
        fila.valor = cifrar(valor) if (secreto and valor) else valor
        fila.cifrado = bool(secreto and valor)
        fila.actualizado, fila.actualizado_por_id = ahora(), actor_id
    db.commit()


# ---------------- Envío ----------------
def enviar(cfg: dict, destinatarios: list[str], asunto: str, cuerpo_html: str, cuerpo_texto: str):
    if not destinatarios:
        raise ErrorCorreo("No hay destinatarios configurados.")
    remitente = cfg["CORREO_REMITENTE"].strip()
    if not remitente:
        raise ErrorCorreo("Falta el correo remitente.")
    if cfg["CORREO_METODO"] == "graph":
        _enviar_graph(remitente, destinatarios, asunto, cuerpo_html)
    else:
        _enviar_smtp(cfg, remitente, destinatarios, asunto, cuerpo_html, cuerpo_texto)


def _enviar_smtp(cfg, remitente, destinatarios, asunto, cuerpo_html, cuerpo_texto):
    host = cfg["CORREO_SMTP_HOST"].strip()
    if not host:
        raise ErrorCorreo("Falta el servidor SMTP.")
    try:
        puerto = int(cfg["CORREO_SMTP_PUERTO"] or 587)
    except ValueError:
        raise ErrorCorreo("El puerto SMTP no es válido.")
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr((cfg["CORREO_REMITENTE_NOMBRE"] or "", remitente))
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(cuerpo_texto)
    msg.add_alternative(cuerpo_html, subtype="html")
    seguridad = cfg["CORREO_SMTP_SEGURIDAD"]
    try:
        if seguridad == "ssl":
            servidor = smtplib.SMTP_SSL(host, puerto, timeout=20, context=ssl.create_default_context())
        else:
            servidor = smtplib.SMTP(host, puerto, timeout=20)
        with servidor:
            if seguridad == "starttls":
                servidor.starttls(context=ssl.create_default_context())
            if cfg["CORREO_SMTP_USUARIO"]:
                servidor.login(cfg["CORREO_SMTP_USUARIO"], cfg["CORREO_SMTP_PASSWORD"])
            servidor.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise ErrorCorreo("El servidor SMTP rechazó el usuario o la contraseña.")
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorCorreo(f"No se pudo enviar por SMTP ({type(e).__name__}: {str(e)[:150]}).")


def _enviar_graph(remitente, destinatarios, asunto, cuerpo_html):
    if not settings.graph_configurado and not settings.microsoft_configurado:
        raise ErrorCorreo("Configura primero la conexión con Microsoft (Configuración → Conexión con Microsoft).")
    try:
        token = microsoft.token_aplicacion()
        with microsoft._cliente() as c:
            r = c.post(f"{settings.microsoft_graph_url}/users/{remitente}/sendMail",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"message": {"subject": asunto, "body": {"contentType": "HTML", "content": cuerpo_html},
                                         "toRecipients": [{"emailAddress": {"address": d}} for d in destinatarios]},
                             "saveToSentItems": False})
    except microsoft.ErrorMicrosoft as e:
        raise ErrorCorreo(e.mensaje)
    except httpx.HTTPError as e:
        raise ErrorCorreo(f"No se pudo contactar a Microsoft ({type(e).__name__}).")
    if r.status_code == 403:
        raise ErrorCorreo("Microsoft negó el envío: falta el permiso de aplicación Mail.Send con consentimiento de administrador.")
    if r.status_code == 404:
        raise ErrorCorreo(f"No existe el buzón remitente {remitente} en Microsoft 365.")
    if r.status_code not in (200, 202):
        raise ErrorCorreo(f"Microsoft Graph respondió HTTP {r.status_code} al enviar el correo.")


# ---------------- Avisos a caseta ----------------
def _plantilla(titulo: str, color: str, filas: list[tuple[str, str]], nota: str) -> str:
    renglones = "".join(
        f'<tr><td style="padding:8px 12px;color:#667085;width:170px;border-bottom:1px solid #eef0f4">{html.escape(k)}</td>'
        f'<td style="padding:8px 12px;font-weight:600;color:#1d2433;border-bottom:1px solid #eef0f4">{html.escape(v)}</td></tr>'
        for k, v in filas if v)
    return f"""<!doctype html><html><body style="margin:0;background:#f4f6fa;font-family:Segoe UI,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:24px 0"><tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;overflow:hidden">
<tr><td style="background:#161e2f;color:#fff;padding:18px 24px;font-size:13px;letter-spacing:.5px">SIP-O · AVISO A CASETA</td></tr>
<tr><td style="padding:20px 24px 6px"><div style="display:inline-block;background:{color};color:#fff;border-radius:4px;padding:4px 10px;font-size:12px;font-weight:600">{html.escape(titulo)}</div></td></tr>
<tr><td style="padding:8px 12px 4px"><table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px">{renglones}</table></td></tr>
<tr><td style="padding:14px 24px 22px;color:#667085;font-size:12px">{html.escape(nota)}</td></tr>
</table></td></tr></table></body></html>"""


def mensaje_permiso(p: Permiso, evento: str) -> tuple[str, str, str]:
    u = p.usuario
    tipo = NOMBRES_TIPO.get(p.tipo, p.tipo)
    if p.tipo == PERMISO_HOME_OFFICE:
        cuando = f"{p.fecha:%d/%m/%Y} al {(p.fecha_fin or p.fecha):%d/%m/%Y}"
        horario = "Día completo (trabajo remoto)"
    else:
        cuando = f"{p.fecha:%d/%m/%Y}"
        horario = f"{p.hora_inicio:%H:%M} a {p.hora_fin:%H:%M} ({p.horas:g} h)"
    cancelado = evento == "permiso_cancelado"
    titulo = f"PERMISO {'CANCELADO' if cancelado else 'AUTORIZADO'} · {tipo.upper()}"
    asunto = f"[Caseta] {'Cancelado' if cancelado else 'Autorizado'}: {tipo} · {u.nombre} · {cuando}"
    filas = [
        ("Empleado", u.nombre), ("No. de nómina", u.numero_empleado), ("Departamento", p.departamento or u.departamento or ""),
        ("Puesto", u.puesto or ""), ("Turno", u.turno.nombre if u.turno else ""), ("Tipo de permiso", tipo),
        ("Fecha", cuando), ("Horario", horario),
        ("Autorizó", p.revisado_por.nombre if p.revisado_por else ""),
    ]
    nota = ("Este permiso fue CANCELADO: ya no está autorizado." if cancelado
            else "Permiso autorizado en el sistema de vacaciones y permisos. Permitir la salida/entrada en el horario indicado.")
    texto = f"{titulo}\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, _plantilla(titulo, "#c62828" if cancelado else "#2e7d32", filas, nota), texto


def _registrar_y_enviar(db: Session, notif: NotificacionCorreo, cfg: dict, html_: str, texto: str):
    notif.intentos += 1
    try:
        enviar(cfg, lista_correos(notif.destinatarios), notif.asunto, html_, texto)
        notif.estado, notif.error = "enviado", None
    except ErrorCorreo as e:
        notif.estado, notif.error = "error", str(e)
        log.warning("Aviso por correo no enviado (notificación %s): %s", notif.id, e)
    except Exception as e:  # noqa: BLE001 - nunca debe romper la aprobación
        notif.estado, notif.error = "error", f"Error inesperado ({type(e).__name__})"
        log.exception("Error inesperado al enviar correo")
    db.commit()


def notificar_permiso(permiso_id: int, evento: str = "permiso_autorizado"):
    """Tarea en segundo plano: avisa a caseta si el aviso está activo para ese tipo de permiso."""
    with SessionLocal() as db:
        cfg = cargar(db)
        p = db.get(Permiso, permiso_id)
        tipos = set(lista_correos(cfg["CORREO_CASETA_TIPOS"]))
        destinatarios = lista_correos(cfg["CORREO_CASETA_DESTINATARIOS"])
        if not p or cfg["CORREO_CASETA_ACTIVO"] != "true" or p.tipo not in tipos or not destinatarios:
            return
        asunto, html_, texto = mensaje_permiso(p, evento)
        notif = NotificacionCorreo(fecha=ahora(), evento=evento, permiso_id=p.id,
                                   destinatarios=", ".join(destinatarios), asunto=asunto[:255])
        db.add(notif)
        db.commit()
        _registrar_y_enviar(db, notif, cfg, html_, texto)


def reintentar(db: Session, notif: NotificacionCorreo):
    cfg = cargar(db)
    if notif.permiso is not None:
        asunto, html_, texto = mensaje_permiso(notif.permiso, notif.evento)
    else:
        asunto, html_, texto = mensaje_prueba()
    notif.destinatarios = ", ".join(lista_correos(cfg["CORREO_CASETA_DESTINATARIOS"])) or notif.destinatarios
    notif.asunto = asunto[:255]
    _registrar_y_enviar(db, notif, cfg, html_, texto)


def mensaje_prueba() -> tuple[str, str, str]:
    filas = [("Sistema", settings.app_descripcion), ("Fecha", f"{ahora():%d/%m/%Y %H:%M} (UTC)")]
    nota = "Correo de prueba: si lo recibes, los avisos a caseta están configurados correctamente."
    return ("[Caseta] Correo de prueba de SIP-O", _plantilla("CORREO DE PRUEBA", "#1f4a86", filas, nota),
            "Correo de prueba de SIP-O.\n" + nota)
