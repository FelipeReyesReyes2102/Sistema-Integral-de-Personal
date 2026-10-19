"""Aprobación en Teams con un flujo de Power Automate llamado por HTTP (un solo flujo para vacaciones y permisos).

1. Cuando una solicitud queda "Solicitado", SIP-O hace POST a la URL del flujo (disparador "Cuando se recibe una
   solicitud HTTP") con el folio, el correo del jefe, un título, los detalles y un token aleatorio de un solo uso.
2. El flujo pide la aprobación en Teams/Outlook y, al responder el jefe, crea un elemento en la lista de SharePoint
   "Decisiones SIP-O" con el folio, el token, la decisión, el comentario y quién respondió.
3. SIP-O revisa esa lista cada minuto y aplica la decisión. SIP-O nunca recibe llamadas desde internet: el servidor
   sigue siendo interno.

Seguridad: la URL del flujo se guarda cifrada (quien la tenga puede iniciar aprobaciones); la decisión solo se acepta
si trae el token de esa solicitud, si el elemento lo creó la cuenta del flujo y si quien respondió puede aprobarla.
"""
import logging
import secrets
import threading
from datetime import datetime, timedelta

import httpx
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from . import microsoft
from .config_dinamica import cifrar, descifrar
from .models import (
    BORRADOR, PERMISO_CONSULTA_MEDICA, RECHAZADO, SOLICITADO, VALIDADO, CanalAprobacion, Permiso, SolicitudAprobacion,
    SolicitudVacaciones, Usuario,
)
from .security import ahora
from .sharepoint import ErrorSharePoint, _graph, _valor_campo, normalizar

log = logging.getLogger("sip.aprobacion")
SEGUNDO_PLANO = True  # las pruebas lo apagan
MAX_INTENTOS = 8
TIPOS = ("vacaciones", "permisos")
COLUMNAS = ("Token", "Decision", "Comentario", "Respondio", "Tipo", "RegistroId")
PERMISOS = {"llegada_tarde": "Llegada tarde", "salida_temprana": "Salida temprana",
            "salida_intermedia": "Salida durante la jornada", "home_office": "Home office"}
NOMINA = {"con_goce": "Con goce de sueldo", "sin_goce": "Sin goce de sueldo", "reposicion": "Reposición de tiempo"}


def _modelo(tipo):
    return SolicitudVacaciones if tipo == "vacaciones" else Permiso


def folio(tipo: str, rid: int) -> str:
    return f"{'VAC' if tipo == 'vacaciones' else 'PER'}-{rid}"


def tipos_de(canal: CanalAprobacion) -> set[str]:
    return {t for t in (canal.tipos or "").split(",") if t in TIPOS}


def canal_activo(db_o_con, sede_id: int | None, tipo: str) -> bool:
    """¿La sede aprueba ese tipo con el flujo HTTP? (lo consulta también la aprobación por listas para no duplicar)."""
    c = db_o_con.execute(select(CanalAprobacion.activo, CanalAprobacion.tipos).where(CanalAprobacion.sede_id == sede_id)).first()
    return bool(c and c.activo and tipo in (c.tipos or "").split(","))


# ---------------- Contenido de la aprobación ----------------
def _f(d):
    return d.strftime("%d/%m/%Y") if d else ""


def contenido(tipo: str, reg) -> dict:
    u = reg.usuario
    jefe = reg.aprobador
    base = {"folio": folio(tipo, reg.id), "tipo": tipo, "registroId": reg.id, "empleado": u.nombre,
            "correoEmpleado": u.email or u.email_personal or "", "correoJefe": (jefe.email or jefe.email_personal) if jefe else "",
            "jefe": jefe.nombre if jefe else "", "sede": u.sede.nombre if u.sede else "",
            "enlace": "https://sip-o.otek.internal/aprobaciones"}
    from .config import settings
    if settings.microsoft_frontend_url:
        base["enlace"] = settings.microsoft_frontend_url.rstrip("/") + "/aprobaciones"
    if tipo == "vacaciones":
        from .services import saldo_periodo
        from sqlalchemy.orm import object_session
        saldo = saldo_periodo(object_session(reg), reg.periodo) if reg.periodo else None
        lineas = [f"**Empleado:** {u.nombre}", f"**Del** {_f(reg.fecha_inicio)} **al** {_f(reg.fecha_fin)}",
                  f"**Días hábiles:** {reg.dias_habiles}"]
        if reg.periodo:
            lineas.append(f"**Periodo:** {reg.periodo.nombre}")
        if saldo:
            lineas.append(f"**Saldo del periodo después de la solicitud:** {round(saldo.dias_disponible, 2):g} días")
        if reg.comentario:
            lineas.append(f"**Comentario:** {reg.comentario}")
        titulo = f"Vacaciones de {u.nombre} ({base['folio']})"
    else:
        ho = reg.tipo == "home_office"
        lineas = [f"**Empleado:** {u.nombre}", f"**Tipo:** {PERMISOS.get(reg.tipo, reg.tipo)}"]
        if ho:
            lineas.append(f"**Del** {_f(reg.fecha)} **al** {_f(reg.fecha_fin or reg.fecha)}")
        else:
            lineas.append(f"**Fecha:** {_f(reg.fecha)} de {reg.hora_inicio:%H:%M} a {reg.hora_fin:%H:%M} ({reg.horas:g} h)")
        if reg.tipo_nomina:
            lineas.append(f"**Nómina:** {NOMINA.get(reg.tipo_nomina, reg.tipo_nomina)}")
        if reg.motivo:
            lineas.append(f"**Motivo:** {reg.motivo}")
        titulo = f"Permiso de {u.nombre} ({base['folio']}): {PERMISOS.get(reg.tipo, reg.tipo)}"
    lineas.append("También puedes resolverla en SIP-O.")
    return {**base, "titulo": titulo[:250], "detalles": "\n\n".join(lineas)}


# ---------------- Cola de envío ----------------
def _encolar(session: Session, _ctx):
    objs = [o for o in (*session.new, *session.dirty)
            if isinstance(o, SolicitudVacaciones) or (isinstance(o, Permiso) and o.tipo != PERMISO_CONSULTA_MEDICA)]
    if not objs:
        return
    con = session.connection()
    canales = {r.sede_id: set((r.tipos or "").split(",")) for r in
               con.execute(select(CanalAprobacion.sede_id, CanalAprobacion.tipos).where(CanalAprobacion.activo))}
    if not canales:
        return
    S, U = SolicitudAprobacion.__table__, Usuario.__table__
    for o in objs:
        tipo = "vacaciones" if isinstance(o, SolicitudVacaciones) else "permisos"
        if o.estado != SOLICITADO:
            continue
        sede = con.execute(select(U.c.sede_id).where(U.c.id == o.usuario_id)).scalar()
        if tipo not in canales.get(sede, set()):
            continue
        if con.execute(select(S.c.id).where(S.c.tipo == tipo, S.c.registro_id == o.id)).scalar():
            continue
        con.execute(S.insert().values(sede_id=sede, tipo=tipo, registro_id=o.id, token=secrets.token_urlsafe(24),
                                      estado="pendiente", intentos=0, creado=ahora()))
        session.info["aprobacion_cola"] = True


def _tras_commit(session: Session):
    if session.info.pop("aprobacion_cola", False) and SEGUNDO_PLANO:
        threading.Thread(target=enviar_pendientes, name="sip-aprobacion", daemon=True).start()


_candado = threading.Lock()


def enviar_pendientes() -> int:
    """POST al flujo de cada solicitud en cola (reintenta con espera creciente)."""
    from .database import SessionLocal
    if not _candado.acquire(blocking=False):
        return 0
    enviados = 0
    try:
        with SessionLocal() as db:
            t = ahora()
            filas = db.scalars(select(SolicitudAprobacion).where(
                SolicitudAprobacion.estado.in_(("pendiente", "error")), SolicitudAprobacion.intentos < MAX_INTENTOS)
                .order_by(SolicitudAprobacion.id).limit(50)).all()
            for s in filas:
                if s.estado == "error" and s.actualizado and t - s.actualizado < timedelta(minutes=2 ** min(s.intentos, 6)):
                    continue
                enviados += _enviar(db, s)
                db.commit()
    finally:
        _candado.release()
    return enviados


def _enviar(db: Session, s: SolicitudAprobacion) -> int:
    reg = db.get(_modelo(s.tipo), s.registro_id)
    canal = db.scalar(select(CanalAprobacion).where(CanalAprobacion.sede_id == s.sede_id))
    s.actualizado = ahora()
    if reg is None or reg.estado != SOLICITADO:
        s.estado = "cerrada"  # se resolvió o canceló antes de enviarse
        return 0
    if not canal or not canal.activo or not canal.flujo_url:
        s.estado, s.error = "error", "La aprobación en Teams no está configurada para la sede."
        s.intentos += 1
        return 0
    datos = contenido(s.tipo, reg)
    if not datos["correoJefe"]:
        s.estado, s.error = "error", "La solicitud no tiene un jefe aprobador con correo."
        s.intentos = MAX_INTENTOS
        return 0
    try:
        with microsoft._cliente() as c:
            r = c.post(descifrar(canal.flujo_url) or "", json={**datos, "token": s.token})
    except httpx.HTTPError as e:
        s.estado, s.error, s.intentos = "error", f"No se pudo contactar al flujo ({type(e).__name__}).", s.intentos + 1
        return 0
    if r.status_code not in (200, 201, 202):
        detalle = ""
        try:
            detalle = " " + str(r.json().get("error", {}).get("message", ""))[:200]
        except ValueError:
            pass
        s.estado, s.error, s.intentos = "error", f"El flujo respondió HTTP {r.status_code}.{detalle}", s.intentos + 1
        return 0
    s.estado, s.error, s.enviado = "enviada", None, ahora()
    return 1


# ---------------- Decisiones ----------------
def revisar_decisiones() -> int:
    """Busca en la lista de decisiones la respuesta de cada solicitud enviada y la aplica."""
    from .database import SessionLocal
    aplicadas = 0
    with SessionLocal() as db:
        for s in db.scalars(select(SolicitudAprobacion).where(SolicitudAprobacion.estado == "enviada")).all():
            reg = db.get(_modelo(s.tipo), s.registro_id)
            if reg is None or reg.estado != SOLICITADO:
                s.estado, s.actualizado = "cerrada", ahora()  # se resolvió en SIP-O antes
                db.commit()
                continue
            canal = db.scalar(select(CanalAprobacion).where(CanalAprobacion.sede_id == s.sede_id))
            if not canal or not canal.lista_id:
                continue
            try:
                r = _graph("GET", f"sites/{canal.sitio_id}/lists/{canal.lista_id}/items?$top=5"
                                  f"&$select=id,createdBy&$expand=fields($select=Title,Token,Decision,Comentario,Respondio)"
                                  f"&$filter=fields/Token eq '{s.token}'")
            except ErrorSharePoint as e:
                log.warning("Aprobación: no se pudo leer la lista de decisiones: %s", e.mensaje[:200])
                return aplicadas
            if r.status_code != 200:
                log.warning("Aprobación: la lista de decisiones respondió HTTP %s", r.status_code)
                continue
            for item in r.json().get("value", []):
                if aplicar(db, s, canal, reg, item):
                    aplicadas += 1
                    break
    return aplicadas


def aplicar(db: Session, s: SolicitudAprobacion, canal: CanalAprobacion, reg, item: dict) -> bool:
    from . import correo
    from .bitacora import asignar_actor
    from .services import puede_revisar

    def nota(t):
        if s.decision_nota != t:
            s.decision_nota, s.actualizado = t, ahora()
            db.commit()
        return False

    f = item.get("fields") or {}
    if (f.get("Token") or "") != s.token:
        return False
    valor = normalizar(_valor_campo(f.get("Decision")) or "")
    if valor in ("approve", "aprobado", "aprobada", "aprobar"):
        nuevo = VALIDADO
    elif valor in ("reject", "rechazado", "rechazada", "rechazar"):
        nuevo = RECHAZADO
    else:
        return nota(f"Decisión no reconocida: «{(_valor_campo(f.get('Decision')) or '')[:40]}».")
    if canal.cuenta_flujo:
        quien = (item.get("createdBy") or {}).get("user") or {}
        if (quien.get("email") or "").lower() != canal.cuenta_flujo.lower():
            return nota(f"Decisión ignorada: la registró {quien.get('displayName') or quien.get('email') or 'otra cuenta'}"
                        f" y no la cuenta del flujo ({canal.cuenta_flujo}).")
    correo_resp = (_valor_campo(f.get("Respondio")) or "").lower()
    revisor = reg.aprobador
    if correo_resp:
        revisor = db.scalar(select(Usuario).where((Usuario.email == correo_resp) | (Usuario.email_personal == correo_resp)))
    if not revisor or not revisor.activo or not puede_revisar(revisor, reg):
        return nota(f"Decisión ignorada: {correo_resp or 'quien respondió'} no puede aprobar esta solicitud en SIP-O.")
    comentario = _valor_campo(f.get("Comentario"))
    asignar_actor(db, revisor, "Teams (Power Automate)")
    reg.estado, reg.revisado_por_id, reg.fecha_revision = nuevo, revisor.id, datetime.now()
    if nuevo == RECHAZADO:
        reg.motivo_rechazo = comentario or "Rechazado desde Teams"
    elif comentario and s.tipo == "permisos":
        reg.observaciones = comentario
    s.estado, s.decision_nota, s.resuelto, s.actualizado = "resuelta", None, ahora(), ahora()
    db.commit()
    db.info.pop("bitacora_actor", None)
    if s.tipo == "permisos" and nuevo == VALIDADO:
        correo.notificar_permiso(reg.id, "permiso_autorizado")
    return True


# ---------------- Configuración ----------------
def conectar_lista(url: str) -> dict:
    """Valida la lista de decisiones (debe tener las columnas Token, Decision, Comentario y Respondio)."""
    from .sharepoint import conectar
    info = conectar(url)
    nombres = {c["nombre"] for c in info["columnas"]}
    faltan = [c for c in ("Token", "Decision", "Comentario", "Respondio") if c not in nombres]
    if faltan:
        raise ErrorSharePoint(f"A la lista le faltan las columnas: {', '.join(faltan)}.")
    return info


def guardar_url(canal: CanalAprobacion, url: str):
    u = url.strip()
    if not u.startswith("https://") or ".logic.azure.com" not in u and "powerplatform.com" not in u and "powerautomate" not in u:
        raise ValueError("Pega la URL HTTP del disparador «Cuando se recibe una solicitud HTTP» del flujo.")
    canal.flujo_url = cifrar(u)


def tick():
    """Tarea de cada minuto: envía la cola y aplica decisiones."""
    enviar_pendientes()
    revisar_decisiones()


def activar():
    event.listen(Session, "after_flush", _encolar)
    event.listen(Session, "after_commit", _tras_commit)
