"""Sedes: a qué sedes tiene acceso cada usuario, sede activa (selector) y fecha local de cada sede.

Reglas:
- Super administrador: todas las sedes; es el único que crea sedes y cambia a un empleado de sede.
- GH (rol "admin"): solo su sede.
- Gerencia GH: su sede y las adicionales que le asigne un super administrador (tabla admin_sedes).
- Demás roles: solo su sede.
El encabezado `X-Sede-Id` (selector de sede del menú) reduce el alcance a una de las sedes permitidas.
"""
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, true
from sqlalchemy.orm import Session, object_session

from .database import get_db
from .models import ROL_GERENCIA_GH, ROL_SUPERADMIN, ZONA_HORARIA_DEFECTO, AdminSede, Sede, Usuario, es_admin
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
        crear_jornadas_base(db, s)
    return s


def crear_jornadas_base(db: Session, sede: Sede):
    """Jornadas iniciales de una sede nueva (se pueden editar después)."""
    from .migraciones import JORNADAS_BASE
    from .models import TipoJornada
    if db.scalar(select(TipoJornada.id).where(TipoJornada.sede_id == sede.id).limit(1)) is None:
        for nombre, horas, bloque, ciclo in JORNADAS_BASE:
            db.add(TipoJornada(sede_id=sede.id, nombre=nombre, horas_dia=horas, bloque_minimo=bloque, usa_ciclo_grupo=ciclo))
        db.commit()


def jornada_por_defecto(db: Session, sede_id: int | None, rol: str) -> int | None:
    """Jornada inicial de un empleado: la de su sede con ciclo de grupo si es de planta; si no, la de lunes a viernes."""
    from .models import TipoJornada
    if not sede_id:
        return None
    return db.scalar(select(TipoJornada.id).where(
        TipoJornada.sede_id == sede_id, TipoJornada.activo.is_(True), TipoJornada.usa_ciclo_grupo.is_(rol == "planta"))
        .order_by(TipoJornada.id).limit(1))


def sedes_administradas(db: Session, user: Usuario) -> set[int] | None:
    """Sedes que el usuario puede consultar como administrador (None = todas)."""
    if user.rol == ROL_SUPERADMIN:
        return None
    ids = {user.sede_id} if user.sede_id else set()
    if user.rol == ROL_GERENCIA_GH:  # GH solo su sede; Gerencia GH también las que le asignen
        ids |= set(db.scalars(select(AdminSede.sede_id).where(AdminSede.usuario_id == user.id)))
    return ids


def admin_permite(user: Usuario, sede_id: int | None) -> bool:
    """¿Este administrador puede gestionar a la gente de esa sede?"""
    if user.rol == ROL_SUPERADMIN:
        return True
    if not es_admin(user):
        return False
    if sede_id == user.sede_id:
        return True
    if user.rol != ROL_GERENCIA_GH:
        return False
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
    if es_admin(user):
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
    ids = sedes_administradas(db, user) if es_admin(user) else {user.sede_id}
    q = select(Sede).order_by(Sede.nombre)
    if ids is not None:
        q = q.where(Sede.id.in_(ids or {-1}))
    return list(db.scalars(q))


def normalizar(texto: str | None) -> str:
    """Para comparar ubicaciones: sin mayúsculas, acentos ni espacios repetidos ("O-TEK MEXICO" = "O-tek México")."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.lower().split())


def sede_por_ubicacion(db: Session, ubicacion: str | None) -> Sede | None:
    """Sede que corresponde a la "Ubicación del trabajo" de Microsoft (sin distinguir mayúsculas ni acentos)."""
    u = normalizar(ubicacion)
    if not u:
        return None
    for s in db.scalars(select(Sede).order_by(Sede.id)):
        if normalizar(s.ubicacion_microsoft) == u or normalizar(s.nombre) == u:
            return s
    return None
