import re
import base64
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import microsoft
from ..config import settings
from ..database import get_db
from ..models import (
    ROL_ADMIN, ROL_GERENCIA_GH, ROL_OFICINA, ROL_PLANTA, ROL_SUPERADMIN, AdminSede, Grupo, PeriodoVacaciones, Sede,
    TipoJornada, Turno, Usuario,
    tiene_correo_corporativo,
)
from ..correo import EMAIL
from ..schemas import AjustePeriodo, EmpleadoMicrosoftOut, PeriodoOut, RegistrarJefeIn, UsuarioIn, UsuarioOut
from ..security import (
    ahora, asignar_password_temporal, auditar, get_current_user, hash_password, limpiar_sesiones_de,
    password_inutilizable, puede_usar_password, require_admin,
)
from ..sedes import Alcance, admin_permite, alcance, crear_jornadas_base, jornada_por_defecto, sede_por_ubicacion
from ..services import (
    asignar_dias_disponibles, empleado_visible, puede_aprobar, puede_aprobar_a, saldo_periodo, sincronizar_periodos,
    usuario_out,
)

TELEFONO = re.compile(r"^\+?[0-9 ()\-]{7,30}$")
router = APIRouter(prefix="/api", tags=["usuarios"])


@router.get("/usuarios", response_model=list[UsuarioOut])
def listar(q: str | None = None, rol: str | None = None, grupo_id: int | None = None,
           activos: bool | None = None, db: Session = Depends(get_db), _=Depends(require_admin),
           alc: Alcance = Depends(alcance)):
    stmt = select(Usuario).where(alc.filtro(Usuario.sede_id)).order_by(Usuario.nombre)
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
    return [_con_saldo(db, u) for u in db.scalars(stmt)]


def _con_saldo(db: Session, u: Usuario) -> UsuarioOut:
    """Datos del empleado con sus días de vacaciones disponibles (periodos vigentes)."""
    out = usuario_out(u)
    vigentes = [s for s in (saldo_periodo(db, p) for p in sincronizar_periodos(db, u)) if s.vigente]
    out.saldo_dias = round(sum(s.dias_disponible for s in vigentes), 2)
    out.saldo_detalle = " · ".join(f"{s.nombre}: {s.dias_disponible:g} d" for s in reversed(vigentes)) or None
    # Días del periodo anterior que todavía no se usan: se pierden al vencer
    anteriores = [s for s in vigentes[:-1] if s.dias_disponible > 0]
    if anteriores:
        out.dias_por_vencer, out.fecha_por_vencer = anteriores[0].dias_disponible, anteriores[0].fecha_vencimiento
    return out


@router.get("/usuarios/microsoft/buscar", response_model=EmpleadoMicrosoftOut)
def buscar_en_microsoft(email: str, request: Request, db: Session = Depends(get_db),
                        admin: Usuario = Depends(require_admin), alc: Alcance = Depends(alcance)):
    """Busca al empleado en Microsoft Entra ID (Graph) para prellenar el alta: datos, jefe y foto."""
    if not settings.graph_configurado:
        raise HTTPException(400, "La consulta a Microsoft no está configurada (MICROSOFT_GRAPH_ENABLED).")
    try:
        datos = microsoft.buscar_empleado(email)
    except microsoft.ErrorMicrosoft as e:
        raise HTTPException(e.status, e.mensaje)
    out = EmpleadoMicrosoftOut(**datos)
    sede = sede_por_ubicacion(db, datos.get("ubicacion"))
    if sede is None and datos.get("ubicacion") and admin.rol == ROL_SUPERADMIN:
        sede = Sede(nombre=datos["ubicacion"].strip()[:120], ubicacion_microsoft=datos["ubicacion"].strip()[:200])
        db.add(sede)
        db.commit()
        crear_jornadas_base(db, sede)
        auditar(db, "sede_creada", actor_id=admin.id, detalle=f"{sede.nombre} (desde Microsoft)", request=request)
        db.commit()
        out.sede_nueva = True
    if sede is not None and alc.permite(sede.id) or (sede is not None and admin_permite(admin, sede.id)):
        out.sede_id, out.sede_nombre = sede.id, sede.nombre
    elif sede is not None:
        out.sede_nombre = sede.nombre  # existe, pero no es una sede que este administrador maneje
    jefe = _jefe_local(db, datos.get("jefe"))
    if jefe:
        out.jefe_registrado_id = jefe.id
        sede_emp = out.sede_id or alc.defecto
        out.jefe_id = jefe.id if puede_aprobar_a(jefe, sede_emp) else None
    existente = db.scalar(select(Usuario).where(or_(Usuario.microsoft_oid == out.oid, func.lower(Usuario.email) == out.email)))
    out.ya_registrado_id = existente.id if existente else None
    return out


def _jefe_local(db: Session, jefe_ms: dict | None) -> Usuario | None:
    """Usuario de SIP-O que corresponde al jefe (manager) indicado por Microsoft, por Object ID o correo."""
    if not jefe_ms:
        return None
    condiciones = []
    if jefe_ms.get("oid"):
        condiciones.append(Usuario.microsoft_oid == jefe_ms["oid"])
    if jefe_ms.get("email"):
        condiciones.append(func.lower(Usuario.email) == jefe_ms["email"])
    return db.scalars(select(Usuario).where(or_(*condiciones))).first() if condiciones else None


def _turno_oficina(db: Session, sede_id: int | None) -> int | None:
    """Turno de oficina por omisión: el único turno activo de 8 horas, si solo hay uno."""
    ids = db.scalars(select(Turno.id).where(Turno.activo.is_(True), Turno.horas_jornada == 8,
                                            Turno.sede_id == sede_id)).all()
    return ids[0] if len(ids) == 1 else None


@router.post("/usuarios/microsoft/registrar-jefe", response_model=UsuarioOut)
def registrar_jefe(data: RegistrarJefeIn, request: Request, db: Session = Depends(get_db),
                   admin: Usuario = Depends(require_admin), alc: Alcance = Depends(alcance)):
    """Da de alta desde Microsoft al jefe de un empleado (como oficinas y marcado como jefe), o marca como jefe
    a un usuario que ya existe. Si se crea, la respuesta trae su contraseña temporal (se muestra una sola vez)."""
    if not settings.graph_configurado:
        raise HTTPException(400, "La consulta a Microsoft no está configurada.")
    email = data.email.strip().lower()
    sede_id = data.sede_id or alc.defecto
    alc.exigir(sede_id)
    existente = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))
    datos = None
    if not existente:
        try:
            datos = microsoft.buscar_empleado(email)
        except microsoft.ErrorMicrosoft as e:
            raise HTTPException(e.status, e.mensaje)
        existente = _jefe_local(db, {"oid": datos["oid"], "email": datos["email"]})
    if existente:
        if not existente.activo:
            raise HTTPException(400, f"{existente.nombre} está registrado pero inactivo; actívalo primero.")
        if existente.rol == ROL_SUPERADMIN and admin.rol != ROL_SUPERADMIN:
            raise HTTPException(403, "Solo un super administrador puede modificar a otro super administrador.")
        if not puede_aprobar_a(existente, sede_id) and existente.sede_id != sede_id:
            raise HTTPException(422, f"{existente.nombre} pertenece a otra sede; los jefes solo pueden tener a cargo "
                                     "personal de su propia sede.")
        if not existente.es_jefe:
            existente.es_jefe = True
            auditar(db, "usuario_marcado_jefe", usuario_id=existente.id, actor_id=admin.id, request=request)
            db.commit()
        return usuario_out(existente)

    nomina = (data.numero_empleado or datos.get("numero_empleado") or "").strip()
    if not nomina:
        raise HTTPException(422, f"Microsoft no tiene el número de nómina de {datos.get('nombre') or email}; "
                                 "indícalo para registrarlo.")
    jefe_de_jefe = _jefe_local(db, datos.get("jefe"))
    u = Usuario(sede_id=sede_id, tipo_jornada_id=jornada_por_defecto(db, sede_id, ROL_OFICINA), numero_empleado=nomina, nombre=datos.get("nombre") or email, email=datos["email"], rol=ROL_OFICINA,
                fecha_ingreso=datos.get("fecha_ingreso") or date.today(), puesto=datos.get("puesto"),
                departamento=datos.get("departamento"), es_jefe=True, activo=True, microsoft_oid=datos["oid"],
                jefe_id=jefe_de_jefe.id if jefe_de_jefe and puede_aprobar_a(jefe_de_jefe, sede_id) else None,
                turno_id=_turno_oficina(db, sede_id), password_hash=password_inutilizable())
    if datos.get("foto"):
        cabecera, contenido = datos["foto"].split(",", 1)
        u.foto, u.foto_tipo = base64.b64decode(contenido), cabecera[5:].split(";")[0]
    temporal = asignar_password_temporal(u) if puede_usar_password(u) else None
    db.add(u)
    _commit(db)
    auditar(db, "usuario_creado", usuario_id=u.id, actor_id=admin.id, detalle=f"{u.email} · jefe desde Microsoft",
            request=request)
    db.commit()
    sincronizar_periodos(db, u)
    out = usuario_out(u)
    if temporal:
        out.password_temporal, out.password_temporal_expira = temporal, u.password_temporal_expira
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
def crear(data: UsuarioIn, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
          alc: Alcance = Depends(alcance)):
    _proteger_superadmin(db, admin, None, data)
    data.sede_id = data.sede_id or alc.defecto
    _validar_sede(db, admin, data.sede_id)
    _validar_jefe(db, data.jefe_id, None, data.sede_id)
    _validar_catalogos(db, data)
    valores = _limpiar(data)
    u = Usuario(**valores, password_hash=password_inutilizable())
    temporal = None
    if data.password:  # contraseña indicada por el administrador: también es temporal
        u.password_hash, u.debe_cambiar_password = hash_password(data.password), True
    elif puede_usar_password(u):
        temporal = asignar_password_temporal(u)  # 6 dígitos aleatorios; se cambia al primer inicio de sesión
    _aplicar_foto(u, data)
    db.add(u)
    _commit(db)
    _guardar_sedes_admin(db, admin, u, data.sedes_admin)
    sincronizar_periodos(db, u)
    if data.dias_disponibles is not None:
        try:
            reparto = asignar_dias_disponibles(db, u, data.dias_disponibles)
        except HTTPException:
            db.rollback()
            db.delete(u)  # el saldo indicado no es válido: no se deja el alta a medias
            db.commit()
            raise
        auditar(db, "saldo_inicial", usuario_id=u.id, actor_id=admin.id,
                detalle=", ".join(f"{n}: {d:g} d" for n, d in reparto), request=request)
    auditar(db, "usuario_creado", usuario_id=u.id, actor_id=admin.id, detalle=f"{u.email or u.email_personal or u.numero_empleado} · {u.rol}", request=request)
    db.commit()
    out = usuario_out(u)
    if temporal:
        out.password_temporal, out.password_temporal_expira = temporal, u.password_temporal_expira
    return out


@router.post("/usuarios/{usuario_id}/password-temporal", response_model=UsuarioOut)
def restablecer_password(usuario_id: int, request: Request, db: Session = Depends(get_db),
                         admin: Usuario = Depends(require_admin)):
    """Genera una nueva contraseña temporal de 6 dígitos (y desbloquea al usuario). Se muestra una sola vez."""
    u = _de_mis_sedes(db, admin, usuario_id)
    if u.rol == ROL_SUPERADMIN and admin.rol != ROL_SUPERADMIN:
        raise HTTPException(403, "Solo un super administrador puede restablecer la contraseña de otro super administrador.")
    if u.id == admin.id:
        raise HTTPException(400, "Para tu propia contraseña usa la opción Contraseña del menú.")
    temporal = asignar_password_temporal(u)
    limpiar_sesiones_de(db, u.id)
    auditar(db, "password_restablecida", usuario_id=u.id, actor_id=admin.id, request=request)
    db.commit()
    out = usuario_out(u)
    out.password_temporal, out.password_temporal_expira = temporal, u.password_temporal_expira
    return out


@router.put("/usuarios/{usuario_id}", response_model=UsuarioOut)
def editar(usuario_id: int, data: UsuarioIn, request: Request, db: Session = Depends(get_db),
           admin: Usuario = Depends(require_admin)):
    u = _de_mis_sedes(db, admin, usuario_id)
    _proteger_superadmin(db, admin, u, data)
    sede_anterior = u.sede_id
    data.sede_id = data.sede_id or u.sede_id
    if data.sede_id != u.sede_id:
        if admin.rol != ROL_SUPERADMIN:
            raise HTTPException(403, "Solo un super administrador puede cambiar a un empleado de sede.")
        _validar_sede(db, admin, data.sede_id)
        # Lo que pertenece a la sede anterior no se lleva a la nueva
        if data.jefe_id and (j := db.get(Usuario, data.jefe_id)) and not puede_aprobar_a(j, data.sede_id):
            data.jefe_id = None
        if data.turno_id and (t := db.get(Turno, data.turno_id)) and t.sede_id != data.sede_id:
            data.turno_id = None
        if data.grupo_id and (g := db.get(Grupo, data.grupo_id)) and g.sede_id != data.sede_id:
            data.grupo_id = None
    _validar_jefe(db, data.jefe_id, u.id, data.sede_id)
    _validar_catalogos(db, data)
    estaba_activo = u.activo
    valores = _limpiar(data)
    if not data.microsoft_oid:
        valores.pop("microsoft_oid", None)  # no desvincular por omisión
    for k, v in valores.items():
        setattr(u, k, v)
    if data.password:  # contraseña indicada por el administrador: se debe cambiar al entrar
        u.password_hash, u.debe_cambiar_password = hash_password(data.password), True
        u.password_temporal_expira = None
    _aplicar_foto(u, data)
    if estaba_activo and not u.activo:
        limpiar_sesiones_de(db, u.id)
    if u.sede_id != sede_anterior:
        # Su personal a cargo se queda en la sede anterior: deja de reportarle
        for sub in db.scalars(select(Usuario).where(Usuario.jefe_id == u.id, Usuario.sede_id != u.sede_id)):
            sub.jefe_id = None
        anterior = db.get(Sede, sede_anterior) if sede_anterior else None
        auditar(db, "cambio_sede", usuario_id=u.id, actor_id=admin.id,
                detalle=f"{anterior.nombre if anterior else '—'} → {u.sede.nombre if u.sede else db.get(Sede, u.sede_id).nombre}",
                request=request)
    auditar(db, "usuario_editado", usuario_id=u.id, actor_id=admin.id,
            detalle=f"{u.email or u.email_personal or u.numero_empleado} · {u.rol}", request=request)
    _commit(db)
    _guardar_sedes_admin(db, admin, u, data.sedes_admin)
    db.refresh(u)
    sincronizar_periodos(db, u)
    if data.dias_disponibles is not None:
        reparto = asignar_dias_disponibles(db, u, data.dias_disponibles)
        auditar(db, "saldo_ajustado", usuario_id=u.id, actor_id=admin.id,
                detalle=", ".join(f"{n}: {d:g} d" for n, d in reparto), request=request)
        db.commit()
    return usuario_out(u)


@router.delete("/usuarios/{usuario_id}", status_code=204)
def desactivar(usuario_id: int, request: Request, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    u = _de_mis_sedes(db, admin, usuario_id)
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
def ajustar_periodo(periodo_id: int, data: AjustePeriodo, db: Session = Depends(get_db),
                    admin: Usuario = Depends(require_admin)):
    p = db.get(PeriodoVacaciones, periodo_id)
    if not p or not admin_permite(admin, p.usuario.sede_id):
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


def _validar_jefe(db: Session, jefe_id: int | None, usuario_id: int | None, sede_id: int | None):
    if not jefe_id:
        return
    if jefe_id == usuario_id:
        raise HTTPException(400, "Un empleado no puede ser su propio jefe")
    jefe = db.get(Usuario, jefe_id)
    if not jefe or not puede_aprobar(jefe):
        raise HTTPException(400, "El jefe seleccionado debe estar activo y marcado como jefe")
    if not puede_aprobar_a(jefe, sede_id):
        raise HTTPException(400, "El jefe debe pertenecer a la misma sede que el empleado.")


def _validar_sede(db: Session, admin: Usuario, sede_id: int | None):
    sede = db.get(Sede, sede_id) if sede_id else None
    if sede is None:
        raise HTTPException(422, "Selecciona la sede del empleado.")
    if not admin_permite(admin, sede.id):
        raise HTTPException(403, "No puedes registrar empleados en esa sede.")
    if not sede.activa:
        raise HTTPException(422, f"La sede {sede.nombre} está inactiva.")


def _validar_catalogos(db: Session, data: UsuarioIn):
    """El turno, el grupo y la jornada deben ser de la sede del empleado."""
    if data.tipo_jornada_id and (j := db.get(TipoJornada, data.tipo_jornada_id)) and j.sede_id != data.sede_id:
        data.tipo_jornada_id = None
    if not data.tipo_jornada_id:
        data.tipo_jornada_id = jornada_por_defecto(db, data.sede_id, data.rol)
    if data.turno_id and (t := db.get(Turno, data.turno_id)) and t.sede_id != data.sede_id:
        raise HTTPException(422, "El turno seleccionado pertenece a otra sede.")
    if data.grupo_id and (g := db.get(Grupo, data.grupo_id)) and g.sede_id != data.sede_id:
        raise HTTPException(422, "El grupo seleccionado pertenece a otra sede.")


def _de_mis_sedes(db: Session, admin: Usuario, usuario_id: int) -> Usuario:
    u = db.get(Usuario, usuario_id)
    if not u or not admin_permite(admin, u.sede_id):
        raise HTTPException(404, "Usuario no encontrado")
    return u


def _guardar_sedes_admin(db: Session, actor: Usuario, u: Usuario, sedes: list[int] | None):
    """Sedes adicionales que gestiona una Gerencia GH (solo lo define un super administrador)."""
    if actor.rol != ROL_SUPERADMIN:
        return
    if sedes is None:
        if u.rol == ROL_GERENCIA_GH:
            return
        sedes = []  # dejó de ser Gerencia GH: ya no gestiona otras sedes
    nuevas = {s for s in sedes if s != u.sede_id and db.get(Sede, s)} if u.rol == ROL_GERENCIA_GH else set()
    actuales = {a.sede_id: a for a in db.scalars(select(AdminSede).where(AdminSede.usuario_id == u.id))}
    for sid, fila in actuales.items():
        if sid not in nuevas:
            db.delete(fila)
    for sid in nuevas - set(actuales):
        db.add(AdminSede(usuario_id=u.id, sede_id=sid))
    db.commit()


def _aplicar_foto(u: Usuario, data: UsuarioIn):
    if data.quitar_foto:
        u.foto, u.foto_tipo = None, None
    elif data.foto:
        cabecera, contenido = data.foto.split(",", 1)
        u.foto = base64.b64decode(contenido)
        u.foto_tipo = cabecera[5:].split(";")[0]


def _limpiar(data: UsuarioIn) -> dict:
    valores = data.model_dump(exclude={"password", "foto", "quitar_foto", "dias_disponibles", "sedes_admin"})
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
    for k in ("direccion", "telefono", "contacto_nombre", "contacto_telefono"):
        valores[k] = (valores.get(k) or "").strip() or None
    for etiqueta, k in (("teléfono", "telefono"), ("número de contacto", "contacto_telefono")):
        if valores[k] and not TELEFONO.match(valores[k]):
            raise HTTPException(422, f"El {etiqueta} no es válido: usa solo números, espacios, guiones, paréntesis o +.")
    if data.rol == "medico":
        valores["puede_consultas"] = False  # el médico ya registra consultas por su rol
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
