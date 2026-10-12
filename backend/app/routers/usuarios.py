import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import microsoft
from ..config import settings
from ..database import get_db
from ..models import ROL_PLANTA, ROL_SUPERADMIN, PeriodoVacaciones, Usuario, tiene_correo_corporativo
from ..correo import EMAIL
from ..schemas import AjustePeriodo, EmpleadoMicrosoftOut, PeriodoOut, UsuarioIn, UsuarioOut
from ..security import (
    auditar, get_current_user, hash_password, limpiar_sesiones_de, password_inutilizable, require_admin,
)
from ..services import empleado_visible, puede_aprobar, saldo_periodo, sincronizar_periodos, usuario_out

router = APIRouter(prefix="/api", tags=["usuarios"])


@router.get("/usuarios", response_model=list[UsuarioOut])
def listar(q: str | None = None, rol: str | None = None, grupo_id: int | None = None,
           activos: bool | None = None, db: Session = Depends(get_db), _=Depends(require_admin)):
    stmt = select(Usuario).order_by(Usuario.nombre)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Usuario.nombre.ilike(like), Usuario.email.ilike(like), Usuario.email_personal.ilike(like),
                              Usuario.numero_empleado.ilike(like)))
    if rol:
        stmt = stmt.where(Usuario.rol == rol)
    if grupo_id:
        stmt = stmt.where(Usuario.grupo_id == grupo_id)
    if activos is not None:
        stmt = stmt.where(Usuario.activo == activos)
    return [usuario_out(u) for u in db.scalars(stmt)]


@router.get("/usuarios/microsoft/buscar", response_model=EmpleadoMicrosoftOut)
def buscar_en_microsoft(email: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    """Busca al empleado en Microsoft Entra ID (Graph) para prellenar el alta: datos, jefe y foto."""
    if not settings.graph_configurado:
        raise HTTPException(400, "La consulta a Microsoft no está configurada (MICROSOFT_GRAPH_ENABLED).")
    try:
        datos = microsoft.buscar_empleado(email)
    except microsoft.ErrorMicrosoft as e:
        raise HTTPException(e.status, e.mensaje)
    out = EmpleadoMicrosoftOut(**datos)
    if datos.get("jefe") and datos["jefe"].get("email"):
        jefe = db.scalar(select(Usuario).where(func.lower(Usuario.email) == datos["jefe"]["email"]))
        out.jefe_id = jefe.id if jefe and puede_aprobar(jefe) else None
    existente = db.scalar(select(Usuario).where(or_(Usuario.microsoft_oid == out.oid, func.lower(Usuario.email) == out.email)))
    out.ya_registrado_id = existente.id if existente else None
    return out


@router.get("/usuarios/{usuario_id}/foto")
def foto(usuario_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    u = db.get(Usuario, usuario_id)
    if not u or u.foto_tipo is None or not u.foto:
        raise HTTPException(404, "Sin foto")
    return Response(u.foto, media_type=u.foto_tipo, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/usuarios/{usuario_id}", response_model=UsuarioOut)
def obtener(usuario_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Administrador: cualquiera. Jefe: solo su personal a cargo."""
    return usuario_out(empleado_visible(db, user, usuario_id))


@router.post("/usuarios", response_model=UsuarioOut, status_code=201)
def crear(data: UsuarioIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    if not data.password and not settings.microsoft_configurado:
        raise HTTPException(400, "La contraseña es obligatoria mientras el inicio con Microsoft no esté configurado")
    _proteger_superadmin(db, admin, None, data)
    _validar_jefe(db, data.jefe_id, None)
    valores = _limpiar(data)
    u = Usuario(**valores, password_hash=hash_password(data.password) if data.password else password_inutilizable())
    _aplicar_foto(u, data)
    db.add(u)
    _commit(db)
    auditar(db, "usuario_creado", usuario_id=u.id, actor_id=admin.id, detalle=f"{u.email or u.email_personal or u.numero_empleado} · {u.rol}", request=request)
    db.commit()
    sincronizar_periodos(db, u)
    return usuario_out(u)


@router.put("/usuarios/{usuario_id}", response_model=UsuarioOut)
def editar(usuario_id: int, data: UsuarioIn, request: Request, db: Session = Depends(get_db),
           admin: Usuario = Depends(require_admin)):
    u = db.get(Usuario, usuario_id)
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    _proteger_superadmin(db, admin, u, data)
    _validar_jefe(db, data.jefe_id, u.id)
    estaba_activo = u.activo
    valores = _limpiar(data)
    if not data.microsoft_oid:
        valores.pop("microsoft_oid", None)  # no desvincular por omisión
    for k, v in valores.items():
        setattr(u, k, v)
    if data.password:
        u.password_hash = hash_password(data.password)
    _aplicar_foto(u, data)
    if estaba_activo and not u.activo:
        limpiar_sesiones_de(db, u.id)
    auditar(db, "usuario_editado", usuario_id=u.id, actor_id=admin.id,
            detalle=f"{u.email or u.email_personal or u.numero_empleado} · {u.rol}", request=request)
    _commit(db)
    db.refresh(u)
    sincronizar_periodos(db, u)
    return usuario_out(u)


@router.delete("/usuarios/{usuario_id}", status_code=204)
def desactivar(usuario_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    u = db.get(Usuario, usuario_id)
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    if u.id == admin.id:
        raise HTTPException(400, "No puedes desactivar tu propio usuario")
    _proteger_superadmin(db, admin, u, desactivar=True)
    u.activo = False
    limpiar_sesiones_de(db, u.id)  # cierra sus sesiones abiertas
    auditar(db, "usuario_desactivado", usuario_id=u.id, actor_id=admin.id, request=request)
    db.commit()


@router.get("/periodos", response_model=list[PeriodoOut])
def periodos(usuario_id: int | None = None, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Periodos y saldos del usuario actual, de su personal a cargo o de cualquiera (administrador)."""
    destino = empleado_visible(db, user, usuario_id)
    lista = sincronizar_periodos(db, destino)
    return [saldo_periodo(db, p) for p in reversed(lista)]


@router.put("/periodos/{periodo_id}/ajuste", response_model=PeriodoOut)
def ajustar_periodo(periodo_id: int, data: AjustePeriodo, db: Session = Depends(get_db), _=Depends(require_admin)):
    p = db.get(PeriodoVacaciones, periodo_id)
    if not p:
        raise HTTPException(404, "Periodo no encontrado")
    p.ajuste_horas = data.ajuste_horas
    p.nota_ajuste = data.nota_ajuste
    db.commit()
    return saldo_periodo(db, p)


def _proteger_superadmin(db: Session, actor: Usuario, objetivo: Usuario | None, data: UsuarioIn | None = None,
                         desactivar: bool = False):
    """Solo un super administrador crea o modifica super administradores; siempre debe quedar uno activo."""
    toca_super = (objetivo is not None and objetivo.rol == ROL_SUPERADMIN) or (data is not None and data.rol == ROL_SUPERADMIN)
    if toca_super and actor.rol != ROL_SUPERADMIN:
        raise HTTPException(403, "Solo un super administrador puede crear o modificar a otro super administrador.")
    if objetivo is not None and objetivo.rol == ROL_SUPERADMIN and objetivo.activo:
        pierde = desactivar or (data is not None and (data.rol != ROL_SUPERADMIN or not data.activo))
        if pierde:
            otros = db.scalar(select(func.count(Usuario.id)).where(
                Usuario.rol == ROL_SUPERADMIN, Usuario.activo.is_(True), Usuario.id != objetivo.id)) or 0
            if otros == 0:
                raise HTTPException(400, "Debe existir al menos un super administrador activo.")


def _validar_jefe(db: Session, jefe_id: int | None, usuario_id: int | None):
    if not jefe_id:
        return
    if jefe_id == usuario_id:
        raise HTTPException(400, "Un empleado no puede ser su propio jefe")
    jefe = db.get(Usuario, jefe_id)
    if not jefe or not puede_aprobar(jefe):
        raise HTTPException(400, "El jefe seleccionado debe estar activo y marcado como jefe")


def _aplicar_foto(u: Usuario, data: UsuarioIn):
    if data.quitar_foto:
        u.foto, u.foto_tipo = None, None
    elif data.foto:
        cabecera, contenido = data.foto.split(",", 1)
        u.foto = base64.b64decode(contenido)
        u.foto_tipo = cabecera[5:].split(";")[0]


def _limpiar(data: UsuarioIn) -> dict:
    valores = data.model_dump(exclude={"password", "foto", "quitar_foto"})
    corporativo = (valores.get("email") or "").strip().lower() or None
    personal = (valores.get("email_personal") or "").strip().lower() or None
    if not tiene_correo_corporativo(data.rol):
        corporativo = None  # planta no tiene correo corporativo
    elif not corporativo:
        raise HTTPException(422, "El correo corporativo es obligatorio para el personal de oficinas.")
    for etiqueta, valor in (("corporativo", corporativo), ("personal", personal)):
        if valor and not EMAIL.match(valor):
            raise HTTPException(422, f"El correo {etiqueta} no es válido.")
    if corporativo and personal and corporativo == personal:
        raise HTTPException(422, "El correo personal debe ser distinto del corporativo.")
    valores["email"], valores["email_personal"] = corporativo, personal
    valores["microsoft_oid"] = (valores.get("microsoft_oid") or "").strip() or None
    if data.rol != ROL_PLANTA:  # grupos y turnos solo aplican a planta
        valores["grupo_id"] = None
    return valores


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe un usuario con ese correo (corporativo o personal), número de nómina o cuenta de Microsoft")


def _no_existe():
    raise HTTPException(404, "Usuario no encontrado")
