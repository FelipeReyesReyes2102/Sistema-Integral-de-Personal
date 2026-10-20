"""Configuración de correo y avisos a caseta de cada sede (la hace su GH desde Configuración).

Cada sede tiene su correo de envío (Microsoft 365 o SMTP, remitente y contraseña cifrada) y sus avisos a caseta.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import correo
from ..database import get_db
from ..models import TIPOS_PERMISO_SOLICITABLES, NotificacionCorreo, Sede, Usuario
from .. import tipos_permiso
from ..config_dinamica import cifrar
from ..security import ahora, auditar, require_admin
from ..sedes import Alcance, alcance

router = APIRouter(prefix="/api/admin/correo", tags=["correo y caseta"])


class CorreoIn(BaseModel):
    caseta_activo: bool = False
    caseta_destinatarios: str = ""
    caseta_tipos: list[str] = Field(default_factory=lambda: list(correo.TIPOS_AVISO_DEFECTO))
    # Servidor de correo (común): solo lo cambia el super administrador; si no se envía, se conserva el actual
    metodo: Literal["smtp", "graph"] | None = None
    remitente: str | None = None
    remitente_nombre: str | None = None
    smtp_host: str | None = None
    smtp_puerto: int | None = Field(None, ge=1, le=65535)
    smtp_seguridad: Literal["starttls", "ssl", "ninguna"] | None = None
    smtp_usuario: str | None = None
    smtp_password: str | None = None   # None o "" = conservar la actual
    borrar_password: bool = False


class PruebaIn(BaseModel):
    destinatario: str | None = None


def _estado(db: Session, sede: Sede, user: Usuario) -> dict:
    c = correo.config_sede(db, sede)
    return {
        "sede_id": sede.id, "sede_nombre": sede.nombre,
        "caseta_activo": sede.caseta_activo,
        "caseta_destinatarios": sede.caseta_destinatarios or "",
        "caseta_tipos": correo.lista_correos(sede.caseta_tipos),
        "metodo": c["CORREO_METODO"],
        "remitente": c["CORREO_REMITENTE"],
        "remitente_nombre": c["CORREO_REMITENTE_NOMBRE"],
        "smtp_host": c["CORREO_SMTP_HOST"],
        "smtp_puerto": int(c["CORREO_SMTP_PUERTO"] or 587),
        "smtp_seguridad": c["CORREO_SMTP_SEGURIDAD"],
        "smtp_usuario": c["CORREO_SMTP_USUARIO"],
        "password_configurada": bool(c["CORREO_SMTP_PASSWORD"]),
        "tipos_disponibles": {t.clave: t.nombre for t in tipos_permiso.de_sede(db, sede.id, solo_activos=True)},
    }


def _sede(db: Session, alc: Alcance) -> Sede:
    sede = db.get(Sede, alc.defecto) if alc.defecto else None
    if sede is None:
        raise HTTPException(404, "Sede no encontrada")
    return sede


@router.get("")
def obtener(db: Session = Depends(get_db), user: Usuario = Depends(require_admin), alc: Alcance = Depends(alcance)):
    return _estado(db, _sede(db, alc), user)


@router.put("")
def guardar(data: CorreoIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
            alc: Alcance = Depends(alcance)):
    sede = _sede(db, alc)
    actual = correo.config_sede(db, sede)  # lo que no se envía se conserva
    data.metodo = data.metodo or actual["CORREO_METODO"]
    data.remitente = actual["CORREO_REMITENTE"] if data.remitente is None else data.remitente
    data.remitente_nombre = actual["CORREO_REMITENTE_NOMBRE"] if data.remitente_nombre is None else data.remitente_nombre
    data.smtp_host = actual["CORREO_SMTP_HOST"] if data.smtp_host is None else data.smtp_host
    data.smtp_puerto = data.smtp_puerto or int(actual["CORREO_SMTP_PUERTO"] or 587)
    data.smtp_seguridad = data.smtp_seguridad or actual["CORREO_SMTP_SEGURIDAD"] or "starttls"
    data.smtp_usuario = actual["CORREO_SMTP_USUARIO"] if data.smtp_usuario is None else data.smtp_usuario
    destinatarios = correo.lista_correos(data.caseta_destinatarios)
    errores = [f"Correo no válido: {d}" for d in destinatarios if not correo.EMAIL.match(d)]
    remitente = data.remitente.strip().lower()
    if remitente and not correo.EMAIL.match(remitente):
        errores.append("El correo remitente no es válido.")
    validos = {t.clave for t in tipos_permiso.de_sede(db, sede.id)}
    tipos = [t for t in data.caseta_tipos if t in validos]
    if data.caseta_activo:
        if not destinatarios:
            errores.append("Agrega al menos un correo del personal de caseta.")
        if not tipos:
            errores.append("Selecciona al menos un tipo de permiso para avisar.")
        if not remitente:
            errores.append("Indica el correo remitente.")
        if data.metodo == "smtp" and not data.smtp_host.strip():
            errores.append("Indica el servidor SMTP.")
    if errores:
        raise HTTPException(422, " ".join(errores))

    sede.caseta_activo = data.caseta_activo
    sede.caseta_destinatarios = ", ".join(destinatarios)
    sede.caseta_tipos = ",".join(tipos)
    sede.correo_metodo, sede.correo_remitente = data.metodo, remitente or None
    sede.correo_remitente_nombre = data.remitente_nombre.strip() or None
    sede.smtp_host, sede.smtp_puerto = data.smtp_host.strip() or None, data.smtp_puerto
    sede.smtp_seguridad, sede.smtp_usuario = data.smtp_seguridad, data.smtp_usuario.strip() or None
    if data.smtp_password:
        sede.smtp_password = cifrar(data.smtp_password)
    elif data.borrar_password:
        sede.smtp_password = None
    elif not sede.smtp_password and actual["CORREO_SMTP_PASSWORD"]:
        sede.smtp_password = cifrar(actual["CORREO_SMTP_PASSWORD"])  # conserva la que heredaba de la general
    auditar(db, "config_correo", actor_id=admin.id,
            detalle=f"{sede.nombre}: correo {data.metodo} · {remitente} · caseta={'activo' if data.caseta_activo else 'inactivo'}",
            request=request)
    db.commit()
    return _estado(db, sede, admin)


@router.post("/prueba")
def prueba(data: PruebaIn, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    """Envía un correo de prueba (a la dirección indicada o a la caseta de la sede) con la configuración guardada."""
    sede = _sede(db, alc)
    cfg = correo.config_sede(db, sede)
    destinatarios = correo.lista_correos(data.destinatario or sede.caseta_destinatarios)
    if not destinatarios:
        raise HTTPException(422, "Indica a qué correo enviar la prueba.")
    if any(not correo.EMAIL.match(d) for d in destinatarios):
        raise HTTPException(422, "El correo de prueba no es válido.")
    asunto, html_, texto = correo.mensaje_prueba()
    notif = NotificacionCorreo(fecha=ahora(), evento="prueba", sede_id=sede.id, destinatarios=", ".join(destinatarios),
                               asunto=asunto)
    db.add(notif)
    db.commit()
    correo._registrar_y_enviar(db, notif, cfg, html_, texto)
    return {"ok": notif.estado == "enviado", "error": notif.error, "destinatarios": notif.destinatarios}


@router.get("/historial")
def historial(limite: int = 50, db: Session = Depends(get_db), _=Depends(require_admin),
              alc: Alcance = Depends(alcance)):
    q = (select(NotificacionCorreo).where(alc.filtro(NotificacionCorreo.sede_id))
         .order_by(NotificacionCorreo.id.desc()).limit(min(max(limite, 1), 200)))
    res = []
    for n in db.scalars(q):
        p = n.permiso
        res.append({
            "id": n.id, "fecha": n.fecha, "evento": n.evento, "asunto": n.asunto, "destinatarios": n.destinatarios,
            "estado": n.estado, "error": n.error, "intentos": n.intentos,
            "empleado": p.usuario.nombre if p and p.usuario else None,
            "tipo": tipos_permiso.nombre(db, p.usuario.sede_id if p.usuario else None, p.tipo) if p else None,
        })
    return res


@router.post("/historial/{nid}/reintentar")
def reintentar(nid: int, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    n = db.get(NotificacionCorreo, nid)
    if not n or not alc.permite(n.sede_id):
        raise HTTPException(404, "Notificación no encontrada")
    correo.reintentar(db, n)
    return {"ok": n.estado == "enviado", "error": n.error}
