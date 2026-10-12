"""Catálogos administrables: turnos, grupos, festivos y tabla de antigüedad."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ROL_PLANTA, Festivo, Grupo, ReglaAntiguedad, Turno, Usuario
from ..schemas import (
    AsignarMiembros, FestivoIn, FestivoOut, GrupoIn, GrupoOut, ReglaIn, ReglaOut, TurnoIn, TurnoOut,
)
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api", tags=["catálogos"])


def _commit(db: Session, msg: str = "Ya existe un registro con ese nombre"):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, msg)


# ---------------- Turnos ----------------
@router.get("/turnos", response_model=list[TurnoOut])
def listar_turnos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.scalars(select(Turno).order_by(Turno.nombre)).all()


@router.post("/turnos", response_model=TurnoOut, status_code=201)
def crear_turno(data: TurnoIn, db: Session = Depends(get_db), _=Depends(require_admin)):
    t = Turno(**data.model_dump())
    db.add(t)
    _commit(db)
    return t


@router.put("/turnos/{turno_id}", response_model=TurnoOut)
def editar_turno(turno_id: int, data: TurnoIn, db: Session = Depends(get_db), _=Depends(require_admin)):
    t = db.get(Turno, turno_id) or _404("Turno")
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    _commit(db)
    return t


@router.delete("/turnos/{turno_id}", status_code=204)
def borrar_turno(turno_id: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    t = db.get(Turno, turno_id) or _404("Turno")
    db.delete(t)
    db.commit()


# ---------------- Grupos ----------------
def _grupo_out(db: Session, g: Grupo) -> GrupoOut:
    out = GrupoOut.model_validate(g)
    out.total_miembros = db.scalar(select(func.count(Usuario.id)).where(Usuario.grupo_id == g.id)) or 0
    return out


@router.get("/grupos", response_model=list[GrupoOut])
def listar_grupos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [_grupo_out(db, g) for g in db.scalars(select(Grupo).order_by(Grupo.nombre))]


@router.post("/grupos", response_model=GrupoOut, status_code=201)
def crear_grupo(data: GrupoIn, db: Session = Depends(get_db), _=Depends(require_admin)):
    _validar_grupo(data)
    g = Grupo(**data.model_dump())
    db.add(g)
    _commit(db)
    return _grupo_out(db, g)


@router.put("/grupos/{grupo_id}", response_model=GrupoOut)
def editar_grupo(grupo_id: int, data: GrupoIn, db: Session = Depends(get_db), _=Depends(require_admin)):
    _validar_grupo(data)
    g = db.get(Grupo, grupo_id) or _404("Grupo")
    for k, v in data.model_dump().items():
        setattr(g, k, v)
    _commit(db)
    return _grupo_out(db, g)


@router.delete("/grupos/{grupo_id}", status_code=204)
def borrar_grupo(grupo_id: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    g = db.get(Grupo, grupo_id) or _404("Grupo")
    db.delete(g)
    db.commit()


@router.put("/grupos/{grupo_id}/miembros", response_model=GrupoOut)
def asignar_miembros(grupo_id: int, data: AsignarMiembros, db: Session = Depends(get_db), _=Depends(require_admin)):
    """Reemplaza la lista de miembros del grupo (solo empleados de planta)."""
    g = db.get(Grupo, grupo_id) or _404("Grupo")
    if data.turno_id is not None and not db.get(Turno, data.turno_id):
        raise HTTPException(404, "Turno no encontrado")
    nuevos = db.scalars(select(Usuario).where(Usuario.id.in_(data.usuario_ids))).all() if data.usuario_ids else []
    no_planta = [u.nombre for u in nuevos if u.rol != ROL_PLANTA]
    if no_planta:
        raise HTTPException(400, f"Solo se pueden asignar empleados de planta: {', '.join(no_planta)}")
    for u in db.scalars(select(Usuario).where(Usuario.grupo_id == g.id)):
        if u.id not in data.usuario_ids:
            u.grupo_id = None
    for u in nuevos:
        u.grupo_id = g.id
        if data.turno_id is not None:
            u.turno_id = data.turno_id
    db.commit()
    return _grupo_out(db, g)


def _validar_grupo(data: GrupoIn):
    if data.tipo_ciclo == "rotativo" and not data.fecha_inicio_ciclo:
        raise HTTPException(400, "Un ciclo rotativo requiere la fecha de inicio del ciclo")
    if data.tipo_ciclo == "semanal" and not data.dias_semana.strip():
        raise HTTPException(400, "Selecciona al menos un día de la semana")


# ---------------- Festivos ----------------
@router.get("/festivos", response_model=list[FestivoOut])
def listar_festivos(anio: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(Festivo).order_by(Festivo.fecha)
    if anio:
        q = q.where(func.extract("year", Festivo.fecha) == anio)
    return db.scalars(q).all()


@router.post("/festivos", response_model=FestivoOut, status_code=201)
def crear_festivo(data: FestivoIn, db: Session = Depends(get_db), _=Depends(require_admin)):
    f = Festivo(**data.model_dump())
    db.add(f)
    db.commit()
    return f


@router.put("/festivos/{festivo_id}", response_model=FestivoOut)
def editar_festivo(festivo_id: int, data: FestivoIn, db: Session = Depends(get_db), _=Depends(require_admin)):
    f = db.get(Festivo, festivo_id) or _404("Festivo")
    for k, v in data.model_dump().items():
        setattr(f, k, v)
    db.commit()
    return f


@router.delete("/festivos/{festivo_id}", status_code=204)
def borrar_festivo(festivo_id: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    f = db.get(Festivo, festivo_id) or _404("Festivo")
    db.delete(f)
    db.commit()


# ---------------- Tabla de antigüedad ----------------
@router.get("/reglas-antiguedad", response_model=list[ReglaOut])
def listar_reglas(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.scalars(select(ReglaAntiguedad).order_by(ReglaAntiguedad.anios_desde)).all()


@router.put("/reglas-antiguedad", response_model=list[ReglaOut])
def reemplazar_reglas(data: list[ReglaIn], db: Session = Depends(get_db), _=Depends(require_admin)):
    orden = sorted(data, key=lambda r: r.anios_desde)
    for i, r in enumerate(orden):
        if r.anios_hasta < r.anios_desde:
            raise HTTPException(400, f"Rango inválido {r.anios_desde}-{r.anios_hasta}")
        if i and r.anios_desde <= orden[i - 1].anios_hasta:
            raise HTTPException(400, "Los rangos de años no deben traslaparse")
    for r in db.scalars(select(ReglaAntiguedad)):
        db.delete(r)
    db.flush()
    for r in orden:
        db.add(ReglaAntiguedad(**r.model_dump()))
    db.commit()
    return db.scalars(select(ReglaAntiguedad).order_by(ReglaAntiguedad.anios_desde)).all()


def _404(nombre: str):
    raise HTTPException(404, f"{nombre} no encontrado")
