"""Configuración de correo y avisos a caseta (administrador y super administrador)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import correo
from ..database import get_db
from ..models import TIPOS_PERMISO_SOLICITABLES, NotificacionCorreo, Usuario
from ..security import ahora, auditar, require_admin

router = APIRouter(prefix="/api/admin/correo", tags=["correo y caseta"])


class CorreoIn(BaseModel):
    caseta_activo: bool = False
    caseta_destinatarios: str = ""
    caseta_tipos: list[str] = Field(default_factory=lambda: list(correo.TIPOS_AVISO_DEFECTO))
    metodo: Literal["smtp", "graph"] = "smtp"
    remitente: str = ""
    remitente_nombre: str = "SIP-O Sistema Integral de Personal"
    smtp_host: str = ""
    smtp_puerto: int = Field(587, ge=1, le=65535)
    smtp_seguridad: Literal["starttls", "ssl", "ninguna"] = "starttls"
    smtp_usuario: str = ""
    smtp_password: str | None = None   # None o "" = conservar la actual
    borrar_password: bool = False


class PruebaIn(BaseModel):
    destinatario: str | None = None


def _estado(db: Session) -> dict:
    c = correo.cargar(db)
    return {
        "caseta_activo": c["CORREO_CASETA_ACTIVO"] == "true",
        "caseta_destinatarios": c["CORREO_CASETA_DESTINATARIOS"],
        "caseta_tipos": correo.lista_correos(c["CORREO_CASETA_TIPOS"]),
        "metodo": c["CORREO_METODO"],
        "remitente": c["CORREO_REMITENTE"],
        "remitente_nombre": c["CORREO_REMITENTE_NOMBRE"],
        "smtp_host": c["CORREO_SMTP_HOST"],
        "smtp_puerto": int(c["CORREO_SMTP_PUERTO"] or 587),
        "smtp_seguridad": c["CORREO_SMTP_SEGURIDAD"],
        "smtp_usuario": c["CORREO_SMTP_USUARIO"],
        "password_configurada": bool(c["CORREO_SMTP_PASSWORD"]),
        "tipos_disponibles": {t: correo.NOMBRES_TIPO[t] for t in TIPOS_PERMISO_SOLICITABLES},
    }


@router.get("")
def obtener(db: Session = Depends(get_db), _=Depends(require_admin)):
    return _estado(db)


@router.put("")
def guardar(data: CorreoIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    destinatarios = correo.lista_correos(data.caseta_destinatarios)
    errores = [f"Correo no válido: {d}" for d in destinatarios if not correo.EMAIL.match(d)]
    remitente = data.remitente.strip().lower()
    if remitente and not correo.EMAIL.match(remitente):
        errores.append("El correo remitente no es válido.")
    tipos = [t for t in data.caseta_tipos if t in TIPOS_PERMISO_SOLICITABLES]
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

    cambios = {
        "CORREO_CASETA_ACTIVO": str(data.caseta_activo).lower(),
        "CORREO_CASETA_DESTINATARIOS": ", ".join(destinatarios),
        "CORREO_CASETA_TIPOS": ",".join(tipos),
        "CORREO_METODO": data.metodo,
        "CORREO_REMITENTE": remitente,
        "CORREO_REMITENTE_NOMBRE": data.remitente_nombre.strip(),
        "CORREO_SMTP_HOST": data.smtp_host.strip(),
        "CORREO_SMTP_PUERTO": str(data.smtp_puerto),
        "CORREO_SMTP_SEGURIDAD": data.smtp_seguridad,
        "CORREO_SMTP_USUARIO": data.smtp_usuario.strip(),
    }
    if data.smtp_password:
        cambios["CORREO_SMTP_PASSWORD"] = data.smtp_password
    elif data.borrar_password:
        cambios["CORREO_SMTP_PASSWORD"] = None
    correo.guardar(db, cambios, admin.id)
    auditar(db, "config_correo", actor_id=admin.id,
            detalle=f"caseta={'activo' if data.caseta_activo else 'inactivo'} · {len(destinatarios)} destinatario(s) · {data.metodo}",
            request=request)
    db.commit()
    return _estado(db)


@router.post("/prueba")
def prueba(data: PruebaIn, db: Session = Depends(get_db), _=Depends(require_admin)):
    """Envía un correo de prueba (a la dirección indicada o a los correos de caseta) con la configuración guardada."""
    cfg = correo.cargar(db)
    destinatarios = correo.lista_correos(data.destinatario or cfg["CORREO_CASETA_DESTINATARIOS"])
    if not destinatarios:
        raise HTTPException(422, "Indica a qué correo enviar la prueba.")
    if any(not correo.EMAIL.match(d) for d in destinatarios):
        raise HTTPException(422, "El correo de prueba no es válido.")
    asunto, html_, texto = correo.mensaje_prueba()
    notif = NotificacionCorreo(fecha=ahora(), evento="prueba", destinatarios=", ".join(destinatarios), asunto=asunto)
    db.add(notif)
    db.commit()
    correo._registrar_y_enviar(db, notif, cfg, html_, texto)
    return {"ok": notif.estado == "enviado", "error": notif.error, "destinatarios": notif.destinatarios}


@router.get("/historial")
def historial(limite: int = 50, db: Session = Depends(get_db), _=Depends(require_admin)):
    q = select(NotificacionCorreo).order_by(NotificacionCorreo.id.desc()).limit(min(max(limite, 1), 200))
    res = []
    for n in db.scalars(q):
        p = n.permiso
        res.append({
            "id": n.id, "fecha": n.fecha, "evento": n.evento, "asunto": n.asunto, "destinatarios": n.destinatarios,
            "estado": n.estado, "error": n.error, "intentos": n.intentos,
            "empleado": p.usuario.nombre if p and p.usuario else None,
            "tipo": correo.NOMBRES_TIPO.get(p.tipo) if p else None,
        })
    return res


@router.post("/historial/{nid}/reintentar")
def reintentar(nid: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    n = db.get(NotificacionCorreo, nid)
    if not n:
        raise HTTPException(404, "Notificación no encontrada")
    correo.reintentar(db, n)
    return {"ok": n.estado == "enviado", "error": n.error}
