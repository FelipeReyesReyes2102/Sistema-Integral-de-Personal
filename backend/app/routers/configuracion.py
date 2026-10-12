"""Configuración de la conexión con Microsoft desde la aplicación (solo super administradores)."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config_dinamica, microsoft
from ..config import settings
from ..database import get_db
from ..models import ROL_ADMIN, ROLES, Usuario
from ..security import auditar, require_superadmin

router = APIRouter(prefix="/api/admin/config", tags=["configuración"])

GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DOMINIO = re.compile(r"^[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+$")
URL = re.compile(r"^https?://[^\s/]+(/[^\s]*)?$")


class ConfigMicrosoftIn(BaseModel):
    microsoft_auth_enabled: bool
    microsoft_tenant_id: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str | None = None  # None o "" = conservar el actual
    borrar_secreto: bool = False
    microsoft_redirect_uri: str = ""
    microsoft_frontend_url: str = ""
    microsoft_scopes: str = "openid profile email User.Read"
    microsoft_graph_enabled: bool = False
    password_login_enabled: bool = True
    password_login_roles: str = ""


def _estado(db: Session) -> dict:
    config_dinamica.refrescar(db, forzar=True)
    s = settings
    return {
        "valores": {
            "microsoft_auth_enabled": s.microsoft_auth_enabled,
            "microsoft_tenant_id": s.microsoft_tenant_id,
            "microsoft_client_id": s.microsoft_client_id,
            "microsoft_redirect_uri": s.microsoft_redirect_uri,
            "microsoft_frontend_url": s.microsoft_frontend_url,
            "microsoft_scopes": s.microsoft_scopes,
            "microsoft_graph_enabled": s.microsoft_graph_enabled,
            "password_login_enabled": s.password_login_enabled,
            "password_login_roles": s.password_login_roles,
        },
        "secreto_configurado": bool(s.microsoft_client_secret),
        "origen": config_dinamica.origenes(db),
        "microsoft_login_configurado": s.microsoft_configurado,
        "microsoft_graph_configurado": s.graph_configurado,
    }


@router.get("/microsoft")
def obtener(db: Session = Depends(get_db), _=Depends(require_superadmin)):
    """Valores efectivos (sin el secreto) y de dónde viene cada uno."""
    return _estado(db)


@router.put("/microsoft")
def guardar(data: ConfigMicrosoftIn, request: Request, db: Session = Depends(get_db),
            admin: Usuario = Depends(require_superadmin)):
    tenant, cliente = data.microsoft_tenant_id.strip(), data.microsoft_client_id.strip()
    redirect, frontend = data.microsoft_redirect_uri.strip(), data.microsoft_frontend_url.strip().rstrip("/")
    roles = ",".join(r.strip() for r in data.password_login_roles.split(",") if r.strip())
    scopes = " ".join(data.microsoft_scopes.split())

    errores = []
    if tenant and not (GUID.match(tenant) or DOMINIO.match(tenant)):
        errores.append("El Id. del directorio debe ser un GUID o un dominio (p. ej. empresa.onmicrosoft.com).")
    if cliente and not GUID.match(cliente):
        errores.append("El Id. de aplicación debe ser un GUID.")
    if redirect and (not URL.match(redirect) or not redirect.endswith("/api/auth/microsoft/callback")):
        errores.append("La URI de redirección debe ser una URL que termine en /api/auth/microsoft/callback.")
    if frontend and not URL.match(frontend):
        errores.append("La URL pública del frontend no es válida.")
    if "openid" not in scopes.split():
        errores.append("Los permisos (scopes) deben incluir openid.")
    desconocidos = [r for r in roles.split(",") if r and r not in ROLES]
    if desconocidos:
        errores.append(f"Roles no válidos para contraseña: {', '.join(desconocidos)} (usa admin, oficina o planta).")
    secreto_final = bool(data.microsoft_client_secret) or (bool(settings.microsoft_client_secret) and not data.borrar_secreto)
    if data.microsoft_auth_enabled and not (tenant and cliente and secreto_final and redirect):
        errores.append("Para habilitar Microsoft se requieren el directorio, el Id. de aplicación, el secreto y la URI de redirección.")

    # Evitar que el administrador se quede fuera: no quitar su acceso con contraseña sin haber
    # comprobado antes que puede entrar con Microsoft.
    yo_con_password = data.password_login_enabled and (not roles or admin.rol in roles.split(","))
    sesion = getattr(request.state, "sesion", None)
    if not yo_con_password and (not sesion or sesion.metodo != "microsoft"):
        errores.append("Para quitar el acceso con contraseña a tu tipo de usuario, primero inicia sesión con "
                       "Microsoft y comprueba que funciona.")
    if errores:
        raise HTTPException(422, " ".join(errores))

    cambios: dict[str, str | None] = {
        "MICROSOFT_AUTH_ENABLED": str(data.microsoft_auth_enabled).lower(),
        "MICROSOFT_TENANT_ID": tenant,
        "MICROSOFT_CLIENT_ID": cliente,
        "MICROSOFT_REDIRECT_URI": redirect,
        "MICROSOFT_FRONTEND_URL": frontend,
        "MICROSOFT_SCOPES": scopes,
        "MICROSOFT_GRAPH_ENABLED": str(data.microsoft_graph_enabled).lower(),
        "PASSWORD_LOGIN_ENABLED": str(data.password_login_enabled).lower(),
        "PASSWORD_LOGIN_ROLES": roles,
    }
    if data.microsoft_client_secret:
        cambios["MICROSOFT_CLIENT_SECRET"] = data.microsoft_client_secret.strip()
    elif data.borrar_secreto:
        cambios["MICROSOFT_CLIENT_SECRET"] = None
    config_dinamica.guardar(db, cambios, admin.id)
    detalle = ", ".join(k for k in cambios if k != "MICROSOFT_CLIENT_SECRET")
    if "MICROSOFT_CLIENT_SECRET" in cambios:
        detalle += " · secreto " + ("actualizado" if cambios["MICROSOFT_CLIENT_SECRET"] else "eliminado")
    auditar(db, "config_microsoft", actor_id=admin.id, detalle=detalle, request=request)
    db.commit()
    return _estado(db)


@router.delete("/microsoft")
def volver_a_env(request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_superadmin)):
    """Borra lo guardado en la aplicación y vuelve a usar los valores de .env."""
    config_dinamica.guardar(db, {clave: None for clave in config_dinamica.CLAVES}, admin.id)
    auditar(db, "config_microsoft", actor_id=admin.id, detalle="restaurado a .env", request=request)
    db.commit()
    return _estado(db)


@router.post("/microsoft/probar")
def probar(db: Session = Depends(get_db), _=Depends(require_superadmin)):
    """Prueba la conexión con la configuración guardada."""
    config_dinamica.refrescar(db, forzar=True)
    try:
        return {"resultados": microsoft.probar_conexion()}
    except Exception as e:  # noqa: BLE001 - se informa sin detalles sensibles
        return {"resultados": [{"nombre": "Conexión", "estado": "error", "detalle": f"Error inesperado ({type(e).__name__})."}]}
