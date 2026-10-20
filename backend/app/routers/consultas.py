"""Consultas del servicio médico de planta.

- El médico registra la consulta: paciente (filtrado por tipo de usuario), síntomas, diagnóstico,
  medicamentos recetados, indicaciones y resultado.
- El paciente ve sus consultas completas (en su calendario y lista).
- El administrador ve los registros completos (cada consulta abierta queda en la auditoría).
- El jefe solo ve que hubo consulta y su horario, nunca la información clínica.
"""
import re
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import incapacidades
from ..busqueda import buscar_usuarios
from ..database import get_db
from ..models import ROL_ADMIN, ROL_MEDICO, ROLES, Auditoria, ConsultaMedica, MedicamentoRecetado, Usuario
from ..models import ROLES_ADMIN, es_admin, es_medico  # noqa: F401
from ..schemas import ConsultaIn, ConsultaOut, ConsultaResumenOut, PacienteOut
from ..security import auditar, get_current_user, require_medico
from ..services import empleado_visible
from ..sedes import Alcance, admin_permite, alcance, normalizar, sedes_visibles

router = APIRouter(prefix="/api/consultas", tags=["servicio médico"])


def _completo(c: ConsultaMedica) -> ConsultaOut:
    o = ConsultaOut.model_validate(c)
    o.paciente_nombre = c.paciente.nombre if c.paciente else None
    o.paciente_numero = c.paciente.numero_empleado if c.paciente else None
    o.paciente_rol = c.paciente.rol if c.paciente else None
    o.paciente_departamento = c.paciente.departamento if c.paciente else None
    o.medico_nombre = c.medico.nombre if c.medico else None
    o.incapacidad = incapacidades.out(c.incapacidad) if c.incapacidad else None
    return o


def _resumen(c: ConsultaMedica) -> ConsultaResumenOut:
    o = ConsultaResumenOut.model_validate(c)
    o.paciente_nombre = c.paciente.nombre if c.paciente else None
    o.medico_nombre = c.medico.nombre if c.medico else None
    o.incapacidad = incapacidades.out(c.incapacidad) if c.incapacidad else None
    return o


def _puede_ver_detalle(user: Usuario, c: ConsultaMedica) -> bool:
    if c.paciente_id == user.id:
        return True
    sede = c.paciente.sede_id if c.paciente else None
    return (es_medico(user) and user.sede_id == sede) or admin_permite(user, sede)


def _sedes_atendidas(db: Session, medico: Usuario) -> set[int | None]:
    """El médico atiende a su sede; GH / Gerencia GH / super admin con permiso, a las sedes que administran."""
    if es_admin(medico):
        return {x.id for x in sedes_visibles(db, medico)} | {medico.sede_id}
    return {medico.sede_id}


@router.get("/pacientes", response_model=list[PacienteOut])
def pacientes(rol: str | None = None, q: str | None = None, limite: int = 30, db: Session = Depends(get_db),
              medico: Usuario = Depends(require_medico)):
    """Búsqueda de pacientes por nombre, número de nómina, puesto, departamento o correo.

    Sin distinguir mayúsculas ni acentos y por palabras ("felipe reyes" encuentra "Felipe de Jesús Reyes Reyes").
    No incluye al propio médico (no puede registrarse consultas a sí mismo)."""
    if rol and rol not in ROLES:
        raise HTTPException(400, "Tipo de usuario no válido")
    encontrados = buscar_usuarios(db, _sedes_atendidas(db, medico), q, excluir_id=medico.id, rol=rol, limite=limite)
    out = []
    for u in encontrados:
        o = PacienteOut.model_validate(u)
        o.tiene_foto = u.foto_tipo is not None
        o.sede_nombre = u.sede.nombre if u.sede else None
        out.append(o)
    return out


@router.get("")
def listar(usuario_id: int | None = None, desde: date | None = None, hasta: date | None = None,
           rol: str | None = None, q: str | None = None, todos: bool = False,
           db: Session = Depends(get_db), user: Usuario = Depends(get_current_user), alc: Alcance = Depends(alcance)):
    """
    - Médico con `todos=true`: todas las consultas (filtros de fecha, tipo de usuario y búsqueda).
    - Sin parámetros: mis consultas (detalle completo).
    - `usuario_id`: consultas de un colaborador (jefe/administrador: solo resumen).
    """
    stmt = select(ConsultaMedica).order_by(ConsultaMedica.fecha.desc(), ConsultaMedica.hora_inicio.desc())
    if todos and (es_medico(user) or es_admin(user)):
        stmt = stmt.join(Usuario, Usuario.id == ConsultaMedica.paciente_id).where(alc.filtro(Usuario.sede_id))
        if rol or q:
            if rol:
                stmt = stmt.where(Usuario.rol == rol)
            if q:
                like = f"%{q.strip()}%"
                stmt = stmt.where(or_(Usuario.nombre.ilike(like), Usuario.numero_empleado.ilike(like)))
    elif (es_medico(user) or es_admin(user)) and usuario_id:
        paciente = db.get(Usuario, usuario_id)
        if not paciente or not (alc.permite(paciente.sede_id) or admin_permite(user, paciente.sede_id)):
            raise HTTPException(404, "Empleado no encontrado")
        stmt = stmt.where(ConsultaMedica.paciente_id == usuario_id)  # historial del paciente
    else:
        stmt = stmt.where(ConsultaMedica.paciente_id == empleado_visible(db, user, usuario_id).id)
    if desde:
        stmt = stmt.where(ConsultaMedica.fecha >= desde)
    if hasta:
        stmt = stmt.where(ConsultaMedica.fecha <= hasta)
    return [(_completo(c) if _puede_ver_detalle(user, c) else _resumen(c)).model_dump(mode="json")
            for c in db.scalars(stmt.limit(500))]


def _texto(c: ConsultaMedica) -> str:
    """Resumen de la consulta para la bitácora (sin síntomas, diagnóstico ni medicamentos)."""
    return f"consulta {c.id} · {c.fecha:%d/%m/%Y} {c.hora_inicio:%H:%M} · {RESULTADOS.get(c.resultado, c.resultado)}"


RESULTADOS = {"regresa_labores": "Regresa a sus labores", "envia_casa": "Se envía a casa", "referido": "Referido a clínica / IMSS"}
EVENTOS = {
    "consulta_registrada": "Consulta registrada", "consulta_editada": "Consulta modificada",
    "consulta_eliminada": "Consulta eliminada", "consulta_vista_admin": "Consulta abierta por GH",
    "incapacidad_generada": "Incapacidad generada", "incapacidad_modificada": "Incapacidad modificada",
    "incapacidad_quitada": "Incapacidad quitada", "incapacidad_validada": "Incapacidad validada",
    "incapacidad_rechazada": "Incapacidad rechazada",
}


@router.get("/bitacora")
def bitacora(desde: date | None = None, hasta: date | None = None, q: str | None = None, tipo: str | None = None,
             db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Bitácora del servicio médico: quién registró, modificó o eliminó cada consulta e incapacidad, y quién validó
    o rechazó las incapacidades. La ven quienes registran consultas (y GH) de las sedes que atienden."""
    if not (es_medico(user) or es_admin(user)):
        raise HTTPException(403, "Solo el servicio médico y GH pueden ver la bitácora de consultas.")
    pacientes_ids = select(Usuario.id).where(Usuario.sede_id.in_([x for x in _sedes_atendidas(db, user) if x is not None] or [-1]))
    eventos = [e for e in EVENTOS if not tipo or e.startswith(tipo)]
    stmt = (select(Auditoria).where(Auditoria.evento.in_(eventos), Auditoria.usuario_id.in_(pacientes_ids))
            .order_by(Auditoria.fecha.desc(), Auditoria.id.desc()))
    if desde:
        stmt = stmt.where(Auditoria.fecha >= datetime.combine(desde, time.min))
    if hasta:
        stmt = stmt.where(Auditoria.fecha < datetime.combine(hasta + timedelta(days=1), time.min))
    palabras = normalizar(q).split()
    nombres: dict[int, Usuario | None] = {}

    def persona(uid):
        if uid not in nombres:
            nombres[uid] = db.get(Usuario, uid) if uid else None
        return nombres[uid]

    res = []
    for a in db.scalars(stmt.limit(2000)):
        paciente, actor = persona(a.usuario_id), persona(a.actor_id)
        if palabras:
            texto = normalizar(" ".join(x for x in (paciente and paciente.nombre, paciente and paciente.numero_empleado,
                                                    actor and actor.nombre, a.detalle) if x))
            if not all(w in texto for w in palabras):
                continue
        m = re.search(r"consulta (\d+)", a.detalle or "")
        consulta = db.get(ConsultaMedica, int(m.group(1))) if m else None
        if consulta is not None and consulta.paciente_id != a.usuario_id:
            consulta = None
        inc = consulta.incapacidad if consulta else None
        res.append({
            "id": a.id, "fecha": a.fecha.isoformat(), "evento": a.evento, "evento_nombre": EVENTOS.get(a.evento, a.evento),
            "actor_nombre": actor.nombre if actor else None, "actor_rol": actor.rol if actor else None,
            "paciente_id": a.usuario_id, "paciente_nombre": paciente.nombre if paciente else None,
            "paciente_numero": paciente.numero_empleado if paciente else None,
            # registros anteriores a esta bitácora solo guardaban "consulta N": se completan con la consulta actual
            "detalle": _texto(consulta) if consulta and re.fullmatch(r"consulta \d+", a.detalle or "") else a.detalle,
            "consulta_id": consulta.id if consulta else None,
            "incapacidad_estado": inc.estado if inc else None,
        })
        if len(res) >= 500:
            break
    return res


@router.get("/{cid}", response_model=ConsultaOut)
def detalle(cid: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    c = db.get(ConsultaMedica, cid)
    if not c or not _puede_ver_detalle(user, c):
        raise HTTPException(404, "Consulta no encontrada")
    if es_admin(user) and c.paciente_id != user.id:
        auditar(db, "consulta_vista_admin", usuario_id=c.paciente_id, actor_id=user.id, detalle=_texto(c),
                request=request)
        db.commit()
    return _completo(c)


def _validar(db: Session, data: ConsultaIn, medico: Usuario) -> Usuario:
    paciente = db.get(Usuario, data.paciente_id)
    if not paciente or not paciente.activo:
        raise HTTPException(404, "El paciente no existe o está inactivo")
    if paciente.id == medico.id:
        raise HTTPException(422, "No puedes registrar una consulta a tu propio nombre")
    if paciente.sede_id not in _sedes_atendidas(db, medico):
        raise HTTPException(422, "El paciente pertenece a una sede que no atiendes.")
    if paciente.sede is not None and not paciente.sede.modulo_consultas:
        raise HTTPException(403, "El servicio médico no está habilitado en la sede del paciente.")
    if data.fecha > date.today():
        raise HTTPException(422, "La fecha de la consulta no puede ser futura")
    if data.hora_fin and data.hora_fin <= data.hora_inicio:
        raise HTTPException(422, "La hora de salida debe ser posterior a la de llegada")
    return paciente


def _aplicar(c: ConsultaMedica, data: ConsultaIn):
    c.paciente_id, c.fecha, c.hora_inicio, c.hora_fin = data.paciente_id, data.fecha, data.hora_inicio, data.hora_fin
    c.sintomas = data.sintomas.strip()
    c.diagnostico = (data.diagnostico or "").strip() or None
    c.indicaciones = (data.indicaciones or "").strip() or None
    c.resultado = data.resultado
    c.medicamentos = [MedicamentoRecetado(**m.model_dump()) for m in data.medicamentos if m.nombre.strip()]


@router.post("", response_model=ConsultaOut, status_code=201)
def crear(data: ConsultaIn, request: Request, tareas: BackgroundTasks, db: Session = Depends(get_db),
          medico: Usuario = Depends(require_medico)):
    paciente = _validar(db, data, medico)
    c = ConsultaMedica(medico_id=medico.id)
    _aplicar(c, data)
    evento, _ = incapacidades.aplicar(db, c, data.incapacidad, paciente, medico)
    avisar = evento == "nueva"
    db.add(c)
    db.flush()
    auditar(db, "consulta_registrada", usuario_id=data.paciente_id, actor_id=medico.id, detalle=_texto(c),
            request=request)
    if avisar:
        auditar(db, "incapacidad_generada", usuario_id=data.paciente_id, actor_id=medico.id,
                detalle=f"consulta {c.id} · {incapacidades.texto(c.incapacidad)}", request=request)
    db.commit()
    if avisar:
        tareas.add_task(incapacidades.notificar, c.incapacidad.id, "incapacidad_solicitada")
    return _completo(c)


@router.put("/{cid}", response_model=ConsultaOut)
def editar(cid: int, data: ConsultaIn, request: Request, tareas: BackgroundTasks, db: Session = Depends(get_db),
           medico: Usuario = Depends(require_medico)):
    c = db.get(ConsultaMedica, cid)
    if not c or not _puede_ver_detalle(medico, c):
        raise HTTPException(404, "Consulta no encontrada")
    paciente = _validar(db, data, medico)
    _aplicar(c, data)
    evento, resumen = incapacidades.aplicar(db, c, data.incapacidad, paciente, medico)
    avisar = evento == "nueva"
    db.flush()
    auditar(db, "consulta_editada", usuario_id=c.paciente_id, actor_id=medico.id, detalle=_texto(c), request=request)
    if evento:
        nombre = {"nueva": "incapacidad_generada", "modificada": "incapacidad_modificada", "quitada": "incapacidad_quitada"}[evento]
        auditar(db, nombre, usuario_id=c.paciente_id, actor_id=medico.id,
                detalle=f"consulta {c.id} · {resumen or incapacidades.texto(c.incapacidad)}", request=request)
    db.commit()
    if avisar:
        tareas.add_task(incapacidades.notificar, c.incapacidad.id, "incapacidad_solicitada")
    return _completo(c)


@router.delete("/{cid}", status_code=204)
def eliminar(cid: int, request: Request, db: Session = Depends(get_db), medico: Usuario = Depends(require_medico)):
    c = db.get(ConsultaMedica, cid)
    if not c or not _puede_ver_detalle(medico, c):
        raise HTTPException(404, "Consulta no encontrada")
    if c.incapacidad is not None and c.incapacidad.estado != "solicitado":
        raise HTTPException(400, "La consulta tiene una incapacidad ya revisada por el jefe; no se puede eliminar.")
    detalle = _texto(c) + (f" · se quitó la {incapacidades.texto(c.incapacidad)}" if c.incapacidad else "")
    auditar(db, "consulta_eliminada", usuario_id=c.paciente_id, actor_id=medico.id, detalle=detalle, request=request)
    db.delete(c)
    db.commit()


@router.get("/resumen/hoy")
def resumen_hoy(db: Session = Depends(get_db), _=Depends(require_medico)):
    hoy = date.today()
    total = db.scalar(select(func.count(ConsultaMedica.id)).where(ConsultaMedica.fecha == hoy)) or 0
    a_casa = db.scalar(select(func.count(ConsultaMedica.id)).where(
        ConsultaMedica.fecha == hoy, ConsultaMedica.resultado == "envia_casa")) or 0
    return {"consultas_hoy": total, "enviados_a_casa_hoy": a_casa}
