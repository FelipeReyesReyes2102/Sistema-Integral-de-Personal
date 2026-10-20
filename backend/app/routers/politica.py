"""Política de vacaciones y permisos de cada sede y sus tipos de jornada.

La configura el GH de la sede (o la Gerencia GH / super administrador en las sedes que gestionan). Todos los
empleados pueden consultar la política de su sede (para saber qué permisos y módulos tienen habilitados).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from .. import tipos_permiso
from ..models import TIPOS_PERMISO_SOLICITABLES, Sede, TipoJornada, Usuario
from ..schemas import JornadaIn, JornadaOut, PoliticaIn
from ..security import auditar, get_current_user, require_admin
from ..sedes import Alcance, admin_permite, alcance
from ..services import empleado_visible, reglas_de_sede

router = APIRouter(prefix="/api", tags=["política de la sede"])


def _politica(db: Session, sede: Sede) -> dict:
    jornadas = [_jornada_out(db, j) for j in db.scalars(
        select(TipoJornada).where(TipoJornada.sede_id == sede.id).order_by(TipoJornada.id))]
    filas, propia = reglas_de_sede(db, sede.id)
    return {
        "sede_id": sede.id, "sede_nombre": sede.nombre, "zona_horaria": sede.zona_horaria,
        "meses_vigencia": sede.meses_vigencia, "equivalencia_horas": sede.equivalencia_horas,
        "dias_anticipacion": sede.dias_anticipacion,
        "tipos_permiso": [t.clave for t in tipos_permiso.de_sede(db, sede.id, solo_activos=True)],
        "permisos_tipos": [{"clave": t.clave, "nombre": t.nombre, "modalidad": t.modalidad, "pide_nomina": t.pide_nomina,
                            "limite_cantidad": t.limite_cantidad, "limite_unidad": t.limite_unidad,
                            "limite_periodo": t.limite_periodo, "max_dias_solicitud": t.max_dias_solicitud,
                            "color": t.color, "base": t.base} for t in tipos_permiso.de_sede(db, sede.id, solo_activos=True)],
        "home_office_max_dias": sede.home_office_max_dias,
        "modulo_consultas": sede.modulo_consultas, "modulo_cumpleanos": sede.modulo_cumpleanos,
        "generacion_dias": sede.generacion_dias or "aniversario",
        "aprobacion_gh_vacaciones": sede.aprobacion_gh_vacaciones, "aprobacion_gh_permisos": sede.aprobacion_gh_permisos,
        "caseta_activo": sede.caseta_activo,
        "jornadas": jornadas,
        "tabla_propia": propia, "tabla": [{"anios_desde": r.anios_desde, "anios_hasta": r.anios_hasta, "dias": r.dias}
                                          for r in filas],
    }


def _jornada_out(db: Session, j: TipoJornada) -> JornadaOut:
    o = JornadaOut.model_validate(j)
    o.empleados = db.scalar(select(func.count(Usuario.id)).where(Usuario.tipo_jornada_id == j.id,
                                                                  Usuario.activo.is_(True))) or 0
    return o


def _sede(db: Session, sede_id: int | None) -> Sede:
    sede = db.get(Sede, sede_id) if sede_id else None
    if sede is None:
        raise HTTPException(404, "Sede no encontrada")
    return sede


@router.get("/politica")
def obtener(usuario_id: int | None = None, sede_id: int | None = None, db: Session = Depends(get_db),
            user: Usuario = Depends(get_current_user), alc: Alcance = Depends(alcance)):
    """Política de la sede activa; con `usuario_id`, la de la sede de ese empleado (si lo puede consultar); con
    `sede_id`, la de una de las sedes que administra."""
    if sede_id and alc.permite(sede_id) or (sede_id and admin_permite(user, sede_id)):
        return _politica(db, _sede(db, sede_id))
    if usuario_id:
        return _politica(db, _sede(db, empleado_visible(db, user, usuario_id).sede_id))
    return _politica(db, _sede(db, alc.defecto))


@router.put("/politica")
def guardar(data: PoliticaIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
            alc: Alcance = Depends(alcance)):
    sede = _sede(db, alc.defecto)
    sede.meses_vigencia, sede.equivalencia_horas = data.meses_vigencia, data.equivalencia_horas
    sede.dias_anticipacion = data.dias_anticipacion
    tipos = tipos_permiso.de_sede(db, sede.id)
    if data.tipos_permiso is not None:  # compatibilidad: activa o desactiva los tipos base
        for t in tipos:
            if t.base:
                t.activo = t.clave in data.tipos_permiso
    if data.home_office_max_dias:
        for t in tipos:
            if t.clave == "home_office":
                t.max_dias_solicitud = data.home_office_max_dias
    tipos_permiso.sincronizar_sede(db, sede)
    sede.modulo_consultas, sede.modulo_cumpleanos = data.modulo_consultas, data.modulo_cumpleanos
    sede.generacion_dias = data.generacion_dias
    sede.aprobacion_gh_vacaciones, sede.aprobacion_gh_permisos = data.aprobacion_gh_vacaciones, data.aprobacion_gh_permisos
    auditar(db, "politica_sede", actor_id=admin.id,
            detalle=f"{sede.nombre}: vigencia {data.meses_vigencia} meses · anticipación {data.dias_anticipacion} d · "
                    f"permisos {sede.tipos_permiso or 'ninguno'} · "
                    f"{'equivalencia en horas' if data.equivalencia_horas else 'días completos'}", request=request)
    db.commit()
    return _politica(db, sede)


@router.post("/jornadas", response_model=JornadaOut, status_code=201)
def crear_jornada(data: JornadaIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
                  alc: Alcance = Depends(alcance)):
    j = TipoJornada(**data.model_dump(), sede_id=_sede(db, alc.defecto).id)
    db.add(j)
    _commit(db)
    auditar(db, "jornada_creada", actor_id=admin.id, detalle=f"{j.nombre} ({j.horas_dia} h)", request=request)
    db.commit()
    return _jornada_out(db, j)


@router.put("/jornadas/{jid}", response_model=JornadaOut)
def editar_jornada(jid: int, data: JornadaIn, request: Request, db: Session = Depends(get_db),
                   admin: Usuario = Depends(require_admin), alc: Alcance = Depends(alcance)):
    j = db.get(TipoJornada, jid)
    if not j or not alc.permite(j.sede_id):
        raise HTTPException(404, "Tipo de jornada no encontrado")
    for k, v in data.model_dump().items():
        setattr(j, k, v)
    _commit(db)
    auditar(db, "jornada_editada", actor_id=admin.id, detalle=f"{j.nombre} ({j.horas_dia} h, bloque {j.bloque_minimo})",
            request=request)
    db.commit()
    return _jornada_out(db, j)


@router.delete("/jornadas/{jid}", status_code=204)
def borrar_jornada(jid: int, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    j = db.get(TipoJornada, jid)
    if not j or not alc.permite(j.sede_id):
        raise HTTPException(404, "Tipo de jornada no encontrado")
    en_uso = db.scalar(select(func.count(Usuario.id)).where(Usuario.tipo_jornada_id == j.id)) or 0
    if en_uso:
        raise HTTPException(400, f"{en_uso} empleado(s) tienen esta jornada; cámbiales la jornada o desactívala.")
    db.delete(j)
    db.commit()


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe un tipo de jornada con ese nombre en la sede.")
