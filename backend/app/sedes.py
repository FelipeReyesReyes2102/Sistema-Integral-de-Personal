"""Sedes: a qué sedes tiene acceso cada usuario, sede activa (selector) y fecha local de cada sede.

Reglas:
- Super administrador: todas las sedes; es el único que crea sedes y cambia a un empleado de sede.
- Administrador: su sede y las adicionales que le asigne un super administrador (tabla admin_sedes).
- Demás roles: solo su sede.
El encabezado `X-Sede-Id` (selector de sede del menú) reduce el alcance a una de las sedes permitidas.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, true
from sqlalchemy.orm import Session, object_session

from .database import get_db
from .models import ROL_ADMIN, ROL_SUPERADMIN, ZONA_HORARIA_DEFECTO, AdminSede, Sede, Usuario
from .security import get_current_user

SEDE_INICIAL = "O-tek México"


def zona(nombre: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(nombre or ZONA_HORARIA_DEFECTO)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(ZONA_HORARIA_DEFECTO)


def ahora_en(sede: Sede | None) -> datetime:
    """Fecha y hora local de la sede (sin zona, para comparar con horas de configuración)."""
    return datetime.now(zona(sede.zona_horaria if sede else None)).replace(tzinfo=None)


def hoy_de(usuario: Usuario | None) -> date:
    """"Hoy" según la zona horaria de la sede del empleado."""
    return ahora_en(usuario.sede if usuario is not None else None).date()


def sede_principal(db: Session) -> Sede:
    """La sede inicial; se crea si no existe (instalaciones nuevas)."""
    s = db.scalar(select(Sede).where(Sede.nombre == SEDE_INICIAL)) or db.scalar(select(Sede).order_by(Sede.id))
    if s is None:
        s = Sede(nombre=SEDE_INICIAL, ubicacion_microsoft=SEDE_INICIAL, zona_horaria=ZONA_HORARIA_DEFECTO, activa=True)
        db.add(s)
        db.commit()
    return s


def sedes_administradas(db: Session, user: Usuario) -> set[int] | None:
    """Sedes que el usuario puede consultar como administrador (None = todas)."""
    if user.rol == ROL_SUPERADMIN:
        return None
    ids = {user.sede_id} if user.sede_id else set()
    if user.rol == ROL_ADMIN:
        ids |= set(db.scalars(select(AdminSede.sede_id).where(AdminSede.usuario_id == user.id)))
    return ids


def admin_permite(user: Usuario, sede_id: int | None) -> bool:
    """¿Este administrador puede gestionar a la gente de esa sede?"""
    if user.rol == ROL_SUPERADMIN:
        return True
    if user.rol != ROL_ADMIN:
        return False
    if sede_id == user.sede_id:
        return True
    db = object_session(user)
    return db is not None and db.get(AdminSede, (user.id, sede_id)) is not None


class Alcance:
    """Sedes visibles en la petición. `ids` None = todas."""

    def __init__(self, user: Usuario, ids: set[int] | None, defecto: int | None):
        self.user, self.ids, self.defecto = user, ids, defecto

    def filtro(self, columna):
        return true() if self.ids is None else columna.in_(self.ids or {-1})

    def permite(self, sede_id: int | None) -> bool:
        return self.ids is None or sede_id in self.ids

    def exigir(self, sede_id: int | None):
        if not self.permite(sede_id):
            raise HTTPException(403, "No tienes acceso a esa sede.")


def alcance(request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)) -> Alcance:
    if user.rol in (ROL_ADMIN, ROL_SUPERADMIN):
        ids = sedes_administradas(db, user)
    else:
        ids = {user.sede_id} if user.sede_id else set()
    elegida = request.headers.get("x-sede-id", "")
    if elegida.isdigit() and (ids is None or int(elegida) in ids):
        ids = {int(elegida)}
    if ids is None:
        defecto = user.sede_id or sede_principal(db).id
    else:
        defecto = int(elegida) if elegida.isdigit() and int(elegida) in ids else (
            user.sede_id if user.sede_id in ids else (min(ids) if ids else user.sede_id))
    return Alcance(user, ids, defecto)


def sedes_visibles(db: Session, user: Usuario) -> list[Sede]:
    ids = sedes_administradas(db, user) if user.rol in (ROL_ADMIN, ROL_SUPERADMIN) else {user.sede_id}
    q = select(Sede).order_by(Sede.nombre)
    if ids is not None:
        q = q.where(Sede.id.in_(ids or {-1}))
    return list(db.scalars(q))


def sede_por_ubicacion(db: Session, ubicacion: str | None) -> Sede | None:
    """Sede que corresponde a la "Ubicación del trabajo" de Microsoft (sin distinguir mayúsculas)."""
    if not ubicacion or not ubicacion.strip():
        return None
    u = ubicacion.strip().lower()
    for s in db.scalars(select(Sede)):
        if (s.ubicacion_microsoft or "").strip().lower() == u or s.nombre.strip().lower() == u:
            return s
    return None
