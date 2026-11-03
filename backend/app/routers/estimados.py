"""Cumpleaños y aniversarios entre compañeros: solo se ven en el calendario con la aprobación de la otra persona.

- Cada quien decide si quiere ver cumpleaños y aniversarios en su calendario (preferencias).
- Para ver los de alguien se le envía una solicitud; si la acepta, su cumpleaños y su aniversario en la empresa
  aparecen en el calendario de quien la pidió. Cualquiera de los dos puede quitar el acceso después.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..busqueda import buscar_usuarios
from ..database import get_db
from ..models import ContactoCalendario, Sede, Usuario
from ..security import ahora, get_current_user

router = APIRouter(prefix="/api/estimados", tags=["cumpleaños y aniversarios"])


def _persona(u: Usuario) -> dict:
    return {"id": u.id, "nombre": u.nombre, "puesto": u.puesto, "departamento": u.departamento,
            "numero_empleado": u.numero_empleado, "tiene_foto": u.foto_tipo is not None,
            "sede_nombre": u.sede.nombre if u.sede else None}


def _fila(c: ContactoCalendario, yo: Usuario) -> dict:
    otro = c.persona if c.solicitante_id == yo.id else c.solicitante
    return {"id": c.id, "estado": c.estado, "creado": c.creado.isoformat() if c.creado else None,
            "respondido": c.respondido.isoformat() if c.respondido else None, "persona": _persona(otro)}


def contar_recibidas(db: Session, user: Usuario) -> int:
    return db.scalar(select(func.count(ContactoCalendario.id)).where(
        ContactoCalendario.persona_id == user.id, ContactoCalendario.estado == "pendiente")) or 0


@router.get("")
def resumen(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Preferencias, solicitudes recibidas, personas que veo (y pendientes que envié) y quién ve las mías."""
    filas = db.scalars(select(ContactoCalendario).where(or_(
        ContactoCalendario.solicitante_id == user.id, ContactoCalendario.persona_id == user.id))
        .order_by(ContactoCalendario.creado.desc())).all()
    return {
        "preferencias": {"ver_cumpleanos": user.ver_cumpleanos, "ver_aniversarios": user.ver_aniversarios},
        "recibidas": [_fila(c, user) for c in filas if c.persona_id == user.id and c.estado == "pendiente"],
        "veo": [_fila(c, user) for c in filas if c.solicitante_id == user.id and c.estado in ("pendiente", "aceptada", "rechazada")],
        "me_ven": [_fila(c, user) for c in filas if c.persona_id == user.id and c.estado == "aceptada"],
    }


class PreferenciasIn(BaseModel):
    ver_cumpleanos: bool = True
    ver_aniversarios: bool = True


@router.put("/preferencias")
def preferencias(data: PreferenciasIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    user.ver_cumpleanos, user.ver_aniversarios = data.ver_cumpleanos, data.ver_aniversarios
    db.commit()
    return data


@router.get("/buscar")
def buscar(q: str | None = None, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Compañeros (de cualquier sede) para enviarles la solicitud, con el estado de la relación si ya existe."""
    sedes = set(db.scalars(select(Sede.id)))
    relaciones = {c.persona_id: c.estado for c in db.scalars(select(ContactoCalendario).where(
        ContactoCalendario.solicitante_id == user.id))}
    return [{**_persona(u), "estado": relaciones.get(u.id)}
            for u in buscar_usuarios(db, sedes, q, excluir_id=user.id, limite=20)]


class SolicitudIn(BaseModel):
    persona_id: int


@router.post("", status_code=201)
def solicitar(data: SolicitudIn, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Pide a una persona ver su cumpleaños y su aniversario en mi calendario."""
    persona = db.get(Usuario, data.persona_id)
    if not persona or not persona.activo:
        raise HTTPException(404, "Persona no encontrada")
    if persona.id == user.id:
        raise HTTPException(422, "Tu cumpleaños y tu aniversario ya aparecen en tu calendario.")
    c = db.scalar(select(ContactoCalendario).where(ContactoCalendario.solicitante_id == user.id,
                                                   ContactoCalendario.persona_id == persona.id))
    if c and c.estado == "aceptada":
        raise HTTPException(409, f"Ya ves el cumpleaños y el aniversario de {persona.nombre}.")
    if c and c.estado == "pendiente":
        raise HTTPException(409, f"Ya le enviaste una solicitud a {persona.nombre}; espera su respuesta.")
    if c is None:
        c = ContactoCalendario(solicitante_id=user.id, persona_id=persona.id)
        db.add(c)
    c.estado, c.creado, c.respondido = "pendiente", ahora(), None  # también reintenta una rechazada
    db.commit()
    return _fila(c, user)


def _mia_recibida(db: Session, cid: int, user: Usuario) -> ContactoCalendario:
    c = db.get(ContactoCalendario, cid)
    if not c or c.persona_id != user.id:
        raise HTTPException(404, "Solicitud no encontrada")
    return c


@router.post("/{cid}/aceptar")
def aceptar(cid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    c = _mia_recibida(db, cid, user)
    if c.estado != "pendiente":
        raise HTTPException(400, "La solicitud ya fue respondida.")
    c.estado, c.respondido = "aceptada", ahora()
    db.commit()
    return _fila(c, user)


@router.post("/{cid}/rechazar")
def rechazar(cid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    c = _mia_recibida(db, cid, user)
    if c.estado != "pendiente":
        raise HTTPException(400, "La solicitud ya fue respondida.")
    c.estado, c.respondido = "rechazada", ahora()
    db.commit()
    return _fila(c, user)


@router.delete("/{cid}", status_code=204)
def quitar(cid: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Quien la pidió deja de ver (o cancela su solicitud); la otra persona le quita el acceso."""
    c = db.get(ContactoCalendario, cid)
    if not c or user.id not in (c.solicitante_id, c.persona_id):
        raise HTTPException(404, "No encontrada")
    db.delete(c)
    db.commit()
