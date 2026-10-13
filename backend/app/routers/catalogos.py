"""Catálogos administrables: turnos, grupos, festivos y tabla de antigüedad."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ROL_PLANTA, Festivo, Grupo, ReglaAntiguedad, Sede, Turno, Usuario
from ..schemas import (
    AsignarMiembros, FestivoIn, FestivoOut, GrupoIn, GrupoOut, ReglaIn, ReglaOut, TurnoIn, TurnoOut,
)
from ..security import get_current_user, require_admin, require_superadmin
from ..sedes import Alcance, alcance, sede_principal
from ..services import reglas_de_sede

router = APIRouter(prefix="/api", tags=["catálogos"])


def _commit(db: Session, msg: str = "Ya existe un registro con ese nombre"):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, msg)


# ---------------- Turnos ----------------
@router.get("/turnos", response_model=list[TurnoOut])
def listar_turnos(db: Session = Depends(get_db), alc: Alcance = Depends(alcance)):
    return db.scalars(select(Turno).where(alc.filtro(Turno.sede_id)).order_by(Turno.nombre)).all()


@router.post("/turnos", response_model=TurnoOut, status_code=201)
def crear_turno(data: TurnoIn, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    t = Turno(**data.model_dump(), sede_id=alc.defecto)
    db.add(t)
    _commit(db)
    return t


@router.put("/turnos/{turno_id}", response_model=TurnoOut)
def editar_turno(turno_id: int, data: TurnoIn, db: Session = Depends(get_db), _=Depends(require_admin),
                 alc: Alcance = Depends(alcance)):
    t = _de_sede(db.get(Turno, turno_id), alc, "Turno")
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    _commit(db)
    return t


@router.delete("/turnos/{turno_id}", status_code=204)
def borrar_turno(turno_id: int, db: Session = Depends(get_db), _=Depends(require_admin),
                 alc: Alcance = Depends(alcance)):
    t = _de_sede(db.get(Turno, turno_id), alc, "Turno")
    db.delete(t)
    db.commit()


# ---------------- Grupos ----------------
def _grupo_out(db: Session, g: Grupo) -> GrupoOut:
    out = GrupoOut.model_validate(g)
    out.total_miembros = db.scalar(select(func.count(Usuario.id)).where(Usuario.grupo_id == g.id)) or 0
    return out


@router.get("/grupos", response_model=list[GrupoOut])
def listar_grupos(db: Session = Depends(get_db), alc: Alcance = Depends(alcance)):
    return [_grupo_out(db, g) for g in db.scalars(select(Grupo).where(alc.filtro(Grupo.sede_id)).order_by(Grupo.nombre))]


@router.post("/grupos", response_model=GrupoOut, status_code=201)
def crear_grupo(data: GrupoIn, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    _validar_grupo(data)
    g = Grupo(**data.model_dump(), sede_id=alc.defecto)
    db.add(g)
    _commit(db)
    return _grupo_out(db, g)


@router.put("/grupos/{grupo_id}", response_model=GrupoOut)
def editar_grupo(grupo_id: int, data: GrupoIn, db: Session = Depends(get_db), _=Depends(require_admin),
                 alc: Alcance = Depends(alcance)):
    _validar_grupo(data)
    g = _de_sede(db.get(Grupo, grupo_id), alc, "Grupo")
    for k, v in data.model_dump().items():
        setattr(g, k, v)
    _commit(db)
    return _grupo_out(db, g)


@router.delete("/grupos/{grupo_id}", status_code=204)
def borrar_grupo(grupo_id: int, db: Session = Depends(get_db), _=Depends(require_admin),
                 alc: Alcance = Depends(alcance)):
    g = _de_sede(db.get(Grupo, grupo_id), alc, "Grupo")
    db.delete(g)
    db.commit()


@router.put("/grupos/{grupo_id}/miembros", response_model=GrupoOut)
def asignar_miembros(grupo_id: int, data: AsignarMiembros, db: Session = Depends(get_db), _=Depends(require_admin),
                     alc: Alcance = Depends(alcance)):
    """Reemplaza la lista de miembros del grupo (solo empleados de planta de la misma sede)."""
    g = _de_sede(db.get(Grupo, grupo_id), alc, "Grupo")
    if data.turno_id is not None and ((t := db.get(Turno, data.turno_id)) is None or t.sede_id != g.sede_id):
        raise HTTPException(404, "Turno no encontrado en la sede del grupo")
    nuevos = db.scalars(select(Usuario).where(Usuario.id.in_(data.usuario_ids))).all() if data.usuario_ids else []
    otra_sede = [u.nombre for u in nuevos if u.sede_id != g.sede_id]
    if otra_sede:
        raise HTTPException(400, f"Solo se pueden asignar empleados de la sede del grupo: {', '.join(otra_sede)}")
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
def listar_festivos(anio: int | None = None, db: Session = Depends(get_db), alc: Alcance = Depends(alcance)):
    q = select(Festivo).where(alc.filtro(Festivo.sede_id)).order_by(Festivo.fecha)
    if anio:
        q = q.where(func.extract("year", Festivo.fecha) == anio)
    return db.scalars(q).all()


@router.post("/festivos", response_model=FestivoOut, status_code=201)
def crear_festivo(data: FestivoIn, db: Session = Depends(get_db), _=Depends(require_admin),
                  alc: Alcance = Depends(alcance)):
    f = Festivo(**data.model_dump(), sede_id=alc.defecto)
    db.add(f)
    db.commit()
    return f


@router.put("/festivos/{festivo_id}", response_model=FestivoOut)
def editar_festivo(festivo_id: int, data: FestivoIn, db: Session = Depends(get_db), _=Depends(require_admin),
                   alc: Alcance = Depends(alcance)):
    f = _de_sede(db.get(Festivo, festivo_id), alc, "Festivo")
    for k, v in data.model_dump().items():
        setattr(f, k, v)
    db.commit()
    return f


@router.delete("/festivos/{festivo_id}", status_code=204)
def borrar_festivo(festivo_id: int, db: Session = Depends(get_db), _=Depends(require_admin),
                   alc: Alcance = Depends(alcance)):
    f = _de_sede(db.get(Festivo, festivo_id), alc, "Festivo")
    db.delete(f)
    db.commit()


# ---------------- Tabla de antigüedad ----------------
def _tabla(db: Session, sede_id: int) -> dict:
    filas, propia = reglas_de_sede(db, sede_id)
    sede = db.get(Sede, sede_id)
    return {"sede_id": sede_id, "sede_nombre": sede.nombre if sede else None, "propia": propia,
            "principal": sede_principal(db).nombre, "reglas": [ReglaOut.model_validate(r) for r in filas]}


@router.get("/reglas-antiguedad")
def listar_reglas(db: Session = Depends(get_db), alc: Alcance = Depends(alcance)):
    """Tabla de días por antigüedad de la sede activa (o la de la sede principal si no tiene una propia)."""
    return _tabla(db, alc.defecto)


@router.delete("/reglas-antiguedad")
def usar_tabla_principal(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    """La sede deja de tener tabla propia y vuelve a usar la de la sede principal."""
    if alc.defecto == sede_principal(db).id:
        raise HTTPException(400, "La sede principal siempre tiene su propia tabla.")
    for r in db.scalars(select(ReglaAntiguedad).where(ReglaAntiguedad.sede_id == alc.defecto)):
        db.delete(r)
    db.commit()
    return _tabla(db, alc.defecto)


@router.put("/reglas-antiguedad")
def reemplazar_reglas(data: list[ReglaIn], db: Session = Depends(get_db), _=Depends(require_admin),
                      alc: Alcance = Depends(alcance)):
    """Reemplaza la tabla de días por antigüedad de la sede activa."""
    sede_id = alc.defecto
    if not data:
        raise HTTPException(400, "La tabla debe tener al menos un rango.")
    orden = sorted(data, key=lambda r: r.anios_desde)
    for i, r in enumerate(orden):
        if r.anios_hasta < r.anios_desde:
            raise HTTPException(400, f"Rango inválido {r.anios_desde}-{r.anios_hasta}")
        if i and r.anios_desde <= orden[i - 1].anios_hasta:
            raise HTTPException(400, "Los rangos de años no deben traslaparse")
    for r in db.scalars(select(ReglaAntiguedad).where(ReglaAntiguedad.sede_id == sede_id)):
        db.delete(r)
    db.flush()
    for r in orden:
        db.add(ReglaAntiguedad(**r.model_dump(), sede_id=sede_id))
    db.commit()
    return _tabla(db, sede_id)


def _404(nombre: str):
    raise HTTPException(404, f"{nombre} no encontrado")


def _de_sede(obj, alc: Alcance, nombre: str):
    """El registro debe existir y pertenecer a una sede que el usuario administra."""
    if obj is None or not alc.permite(obj.sede_id):
        _404(nombre)
    return obj
