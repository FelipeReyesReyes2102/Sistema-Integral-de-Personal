"""Biblioteca de SharePoint donde se guardan las fotos de los empleados (solo super administrador, global)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import fotos
from ..database import get_db
from ..models import Usuario
from ..security import auditar, require_superadmin

router = APIRouter(prefix="/api/fotos-sharepoint", tags=["fotos"])


class ConectarIn(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    carpeta: str | None = Field(None, max_length=200)


class ActivoIn(BaseModel):
    activo: bool


def _estado(db: Session) -> dict:
    c = fotos.config(db) or {}
    return {"conectada": bool(c.get("drive_id")), "activo": bool(c.get("activo")), "url": c.get("url"),
            "sitio_nombre": c.get("sitio_nombre"), "drive_nombre": c.get("drive_nombre"), "carpeta": c.get("carpeta"),
            "web_url": c.get("web_url"), "en_servidor": fotos.pendientes(db), "en_sharepoint": fotos.en_sharepoint(db)}


@router.get("")
def obtener(db: Session = Depends(get_db), _=Depends(require_superadmin)):
    return _estado(db)


@router.put("/conectar")
def conectar(data: ConectarIn, request: Request, db: Session = Depends(get_db),
             admin: Usuario = Depends(require_superadmin)):
    try:
        datos = fotos.conectar(data.url, data.carpeta)
    except fotos.ErrorFotos as e:
        raise HTTPException(422, e.mensaje)
    anterior = fotos.config(db) or {}
    datos["activo"] = bool(anterior.get("activo")) and anterior.get("drive_id") == datos["drive_id"]
    fotos.guardar_config(db, datos, admin.id)
    auditar(db, "fotos_sharepoint_conectada", actor_id=admin.id,
            detalle=f"{datos.get('sitio_nombre')} · {datos.get('drive_nombre')}/{datos['carpeta']}", request=request)
    db.commit()
    return _estado(db)


@router.put("/activo")
def activar(data: ActivoIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_superadmin)):
    c = fotos.config(db)
    if not c or not c.get("drive_id"):
        raise HTTPException(400, "Conecta primero la biblioteca de SharePoint.")
    c["activo"] = data.activo
    fotos.guardar_config(db, c, admin.id)
    auditar(db, "fotos_sharepoint_" + ("activada" if data.activo else "pausada"), actor_id=admin.id, request=request)
    db.commit()
    return _estado(db)


@router.post("/mover")
def mover(request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_superadmin)):
    """Sube a SharePoint las fotos que siguen en el servidor y las borra del servidor al confirmarse cada una."""
    try:
        res = fotos.mover_pendientes(db)
    except fotos.ErrorFotos as e:
        raise HTTPException(400, e.mensaje)
    auditar(db, "fotos_movidas_sharepoint", actor_id=admin.id,
            detalle=f"{res['movidas']} movidas · {res['pendientes']} siguen en el servidor", request=request)
    db.commit()
    return {**_estado(db), **res}


@router.delete("")
def desconectar(request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_superadmin)):
    """Deja de usar la biblioteca para fotos nuevas. Las que ya están en SharePoint se siguen leyendo de ahí."""
    fotos.guardar_config(db, None, admin.id)
    auditar(db, "fotos_sharepoint_desconectada", actor_id=admin.id, request=request)
    db.commit()
    return _estado(db)
