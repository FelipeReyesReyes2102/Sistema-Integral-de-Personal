"""Cadenas de aprobación personalizadas por tipo de permiso.

- GH arma por sede flujos con nombre (p. ej. "Jefe → TI → GH") y asigna uno a cada tipo de permiso.
- Al enviarse un permiso, los pasos del flujo se copian al permiso (solicitud_pasos) y se resuelve quién aprueba
  cada uno; cambiar la configuración después no afecta lo que ya está en curso.
- Aprobar cierra el paso actual y activa el siguiente; al aprobarse el último, el permiso queda validado.
  Rechazar en cualquier paso termina la solicitud. En los pasos de grupo (GH, TI) basta con que apruebe uno.
- GH de la sede siempre puede resolver directamente (los pasos que faltaban quedan omitidos).
- Cada paso que se activa avisa por correo a quien lo aprueba y, si el paso va a Teams, genera su propia tarjeta.
- Sin flujo asignado (o con los permisos registrados en caseta) se sigue la regla de la sede: jefe, o jefe y después GH.
"""
import logging
import threading
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, event, or_, select
from sqlalchemy.orm import Session, object_session

from .models import (
    SOLICITADO, VALIDADO, FlujoAprobacion, NotificacionCorreo, PasoSolicitud, Permiso, TipoPermisoSede, Usuario, es_admin,
)
from .security import ahora
from .sedes import admin_permite

log = logging.getLogger("sip.flujos")
SEGUNDO_PLANO = True  # las pruebas lo apagan para enviar los avisos en el mismo hilo

APROBADORES = {"jefe": "Jefe directo", "jefe_del_jefe": "Jefe del jefe", "gh": "GH de la sede", "ti": "TI",
               "usuario": "Persona específica"}
INDIVIDUALES = ("jefe", "jefe_del_jefe", "usuario")
EN_ESPERA, PENDIENTE, APROBADO, RECHAZADO, OMITIDO = "en_espera", "pendiente", "aprobado", "rechazado", "omitido"


def etiqueta(aprobador: str, usuario: Usuario | None = None) -> str:
    if aprobador == "usuario" and usuario is not None:
        return usuario.nombre
    return APROBADORES.get(aprobador, aprobador)


def flujo_de_tipo(db: Session, sede_id: int | None, clave: str) -> FlujoAprobacion | None:
    t = db.scalar(select(TipoPermisoSede).where(TipoPermisoSede.sede_id == sede_id, TipoPermisoSede.clave == clave))
    f = db.get(FlujoAprobacion, t.flujo_id) if t is not None and t.flujo_id else None
    return f if f is not None and f.activo and f.pasos else None


def candidatos(db: Session, aprobador: str, usuario_id: int | None, permiso: Permiso) -> list[Usuario]:
    """Quién puede aprobar un paso (nunca el propio solicitante ni personas inactivas)."""
    emp = permiso.usuario or db.get(Usuario, permiso.usuario_id)
    jefe = db.get(Usuario, permiso.aprobador_id) if permiso.aprobador_id else emp.jefe
    if aprobador == "jefe":
        lista = [jefe]
    elif aprobador == "jefe_del_jefe":
        lista = [jefe.jefe if jefe is not None else None]
    elif aprobador == "gh":
        from .incapacidades import gh_de_sede
        lista = gh_de_sede(db, emp.sede_id)
    elif aprobador == "ti":
        lista = list(db.scalars(select(Usuario).where(Usuario.activo.is_(True), Usuario.puede_ti.is_(True),
                                                      Usuario.sede_id == emp.sede_id)))
    elif aprobador == "usuario":
        lista = [db.get(Usuario, usuario_id) if usuario_id else None]
    else:
        lista = []
    return [u for u in lista if u is not None and u.activo and u.id != emp.id]


def candidatos_paso(db: Session, paso: PasoSolicitud) -> list[Usuario]:
    if paso.aprobador in INDIVIDUALES:
        u = db.get(Usuario, paso.usuario_id) if paso.usuario_id else None
        return [u] if u is not None and u.activo else []
    return candidatos(db, paso.aprobador, None, paso.permiso)


def iniciar(db: Session, permiso: Permiso):
    """Copia al permiso los pasos del flujo de su tipo (si tiene) y activa el primero."""
    if permiso.pasos or permiso.registrado_por_id:  # ya iniciado, o retardo de caseta (sigue su propio flujo)
        return
    emp = permiso.usuario or db.get(Usuario, permiso.usuario_id)
    flujo = flujo_de_tipo(db, emp.sede_id, permiso.tipo)
    if flujo is None:
        return
    for fp in flujo.pasos:
        lista = candidatos(db, fp.aprobador, fp.usuario_id, permiso)
        nombre = etiqueta(fp.aprobador, fp.usuario)
        if not lista and fp.si_falta == "bloquear":
            raise HTTPException(422, f"No hay quién apruebe el paso «{nombre}» del flujo «{flujo.nombre}». "
                                     "Revisa el jefe asignado o pide a GH que ajuste el flujo.")
        permiso.pasos.append(PasoSolicitud(
            orden=fp.orden, aprobador=fp.aprobador, etiqueta=nombre, teams=fp.teams,
            usuario_id=lista[0].id if lista and fp.aprobador in INDIVIDUALES else None,
            estado=EN_ESPERA if lista else OMITIDO))
    if _activar_siguiente(permiso) is None:
        raise HTTPException(422, f"El flujo «{flujo.nombre}» no tiene a nadie que pueda aprobar esta solicitud.")
    _paso_activado(db, permiso, inicial=True)


def _paso_activado(db: Session, permiso: Permiso, inicial: bool):
    """Aviso por correo al aprobador y, si el paso va a Teams, su tarjeta (el primer paso la genera el envío normal)."""
    db.info.setdefault("flujos_avisar", set()).add(permiso.id)
    paso = actual(permiso)
    if not inicial and paso is not None and paso.teams:
        from .aprobacion_flujo import reencolar as tarjeta_http
        from .sharepoint import reencolar as tarjeta_lista
        tarjeta_http(db, permiso)
        tarjeta_lista(db, permiso)


def actual(permiso: Permiso) -> PasoSolicitud | None:
    return next((p for p in permiso.pasos if p.estado == PENDIENTE), None)


def _activar_siguiente(permiso: Permiso) -> PasoSolicitud | None:
    sig = next((p for p in permiso.pasos if p.estado == EN_ESPERA), None)
    if sig is not None:
        sig.estado = PENDIENTE
    return sig


def _decidir(paso: PasoSolicitud, estado: str, actor: Usuario, canal: str, comentario: str | None = None):
    paso.estado, paso.decidido_por_id, paso.fecha, paso.canal = estado, actor.id, datetime.now(), canal
    paso.comentario = (comentario or "").strip() or None


def puede_decidir(actor: Usuario, permiso: Permiso) -> bool:
    """¿Le toca al actor el paso actual?"""
    paso = actual(permiso)
    if paso is None or actor.id == permiso.usuario_id:
        return False
    return any(u.id == actor.id for u in candidatos_paso(object_session(permiso), paso))


def gh_puede(actor: Usuario, permiso: Permiso) -> bool:
    return es_admin(actor) and actor.id != permiso.usuario_id and \
        admin_permite(actor, permiso.usuario.sede_id if permiso.usuario else None)


def aprobar(permiso: Permiso, actor: Usuario, canal: str = "sip", comentario: str | None = None) -> bool:
    """Aprueba el paso actual. Devuelve True si el permiso quedó validado (era el último paso o lo resolvió GH)."""
    db = object_session(permiso)
    paso = actual(permiso)
    if paso is not None and puede_decidir(actor, permiso):
        _decidir(paso, APROBADO, actor, canal, comentario)
        while (sig := _activar_siguiente(permiso)) is not None:
            if not any(u.id == actor.id for u in candidatos_paso(db, sig)):
                _paso_activado(db, permiso, inicial=False)
                return False
            _decidir(sig, APROBADO, actor, canal, "Aprobado junto con el paso anterior (misma persona).")
    elif gh_puede(actor, permiso):
        for p in permiso.pasos:
            if p.estado == PENDIENTE:
                _decidir(p, APROBADO, actor, canal, comentario or "Validado directamente por GH.")
            elif p.estado == EN_ESPERA:
                p.estado = OMITIDO
    else:
        raise HTTPException(403, "Este permiso no te toca aprobarlo en el paso actual.")
    permiso.estado, permiso.revisado_por_id, permiso.fecha_revision = VALIDADO, actor.id, datetime.now()
    return True


def rechazar(permiso: Permiso, actor: Usuario, canal: str = "sip", comentario: str | None = None):
    """Marca el rechazo en el paso actual (el estado del permiso lo cambia quien llama)."""
    paso = actual(permiso)
    if paso is not None:
        _decidir(paso, RECHAZADO, actor, canal, comentario)


def acepta_teams(permiso) -> bool:
    """¿El paso actual de la cadena se puede resolver desde Teams?"""
    if not getattr(permiso, "pasos", None):
        return True
    paso = actual(permiso)
    return paso is not None and paso.teams


def correos_actuales(permiso) -> str | None:
    """Correos de quienes aprueban el paso actual, separados por ';' (Power Automate los acepta así)."""
    paso = actual(permiso) if getattr(permiso, "pasos", None) else None
    if paso is None:
        return None
    correos = [u.email or u.email_personal for u in candidatos_paso(object_session(permiso), paso)]
    return ";".join(c for c in correos if c) or None


def asignados(user: Usuario, solo_pendientes: bool):
    """Condición SQL de los permisos que le tocan (o le tocaron) al usuario como aprobador."""
    sin_cadena = ~Permiso.pasos.any()
    from .services import del_grupo
    legado = and_(or_(Permiso.aprobador_id == user.id, Permiso.usuario_id.in_(del_grupo(user.id))), sin_cadena)
    if solo_pendientes:
        legado = and_(legado, Permiso.aprobado_jefe_id.is_(None))
    mio = PasoSolicitud.usuario_id == user.id
    if getattr(user, "puede_ti", False):
        de_mi_sede = Permiso.usuario_id.in_(select(Usuario.id).where(Usuario.sede_id == user.sede_id))
        mio = or_(mio, and_(PasoSolicitud.aprobador == "ti", de_mi_sede))
    cadena = Permiso.pasos.any(and_(PasoSolicitud.estado == PENDIENTE, mio))
    if solo_pendientes:
        return or_(legado, cadena)
    return or_(legado, cadena, Permiso.pasos.any(PasoSolicitud.decidido_por_id == user.id))


def participa(user: Usuario, permiso: Permiso) -> bool:
    """¿Puede ver el permiso por ser (o haber sido) aprobador de alguno de sus pasos?"""
    if not permiso.pasos:
        return False
    return puede_decidir(user, permiso) or any(
        p.usuario_id == user.id or p.decidido_por_id == user.id for p in permiso.pasos)


# ---------------- Aviso por correo al aprobador del paso ----------------
def mensaje_paso(p: Permiso, paso: PasoSolicitud) -> tuple[str, str, str]:
    from . import correo, tipos_permiso
    db = object_session(p)
    u = p.usuario
    tipo = tipos_permiso.nombre(db, u.sede_id, p.tipo)
    if tipos_permiso.por_dias(db, u.sede_id, p.tipo):
        cuando = f"{p.fecha:%d/%m/%Y} al {(p.fecha_fin or p.fecha):%d/%m/%Y}"
    else:
        cuando = f"{p.fecha:%d/%m/%Y} de {p.hora_inicio:%H:%M} a {p.hora_fin:%H:%M} ({p.horas:g} h)"
        from . import lotes
        if (dias := lotes.texto_fechas(db, p)):
            cuando = f"{dias} · de {p.hora_inicio:%H:%M} a {p.hora_fin:%H:%M} ({p.horas:g} h cada día)"
    activos = [x for x in p.pasos if x.estado != OMITIDO]
    n = next((i for i, x in enumerate(activos, 1) if x is paso), 1)
    previos = [f"{x.etiqueta}: {x.decidido_por.nombre if x.decidido_por else '—'}" for x in p.pasos if x.estado == APROBADO]
    titulo = f"PERMISO POR APROBAR · PASO {n} DE {len(activos)}"
    asunto = f"[SIP-O] Permiso por aprobar ({paso.etiqueta}) · {tipo} · {u.nombre}"
    filas = [("Empleado", u.nombre), ("No. de nómina", u.numero_empleado), ("Tipo de permiso", tipo), ("Fecha", cuando),
             ("Motivo", p.motivo or ""), ("Te toca como", paso.etiqueta), ("Ya aprobaron", ", ".join(previos))]
    nota = ("Entra a SIP-O → Por aprobar → Permisos para aprobarlo o rechazarlo"
            + (", o respóndelo desde Teams." if paso.teams else "."))
    html_ = correo._plantilla(titulo, "#a35d00", filas, nota, encabezado="SIP-O · APROBACIÓN DE PERMISO")
    texto = f"{titulo}\n\n" + "\n".join(f"{k}: {v}" for k, v in filas if v) + f"\n\n{nota}\n"
    return asunto, html_, texto


def avisar(ids: set[int]):
    """Correo a quienes aprueban el paso actual de cada permiso (nunca impide la aprobación)."""
    from . import correo
    from .database import SessionLocal
    with SessionLocal() as db:
        for pid in ids:
            p = db.get(Permiso, pid)
            if p is not None and p.lote and p.lote != p.id:
                continue  # día de un lote: el aviso va con el principal
            paso = actual(p) if p is not None and p.estado == SOLICITADO else None
            if paso is None:
                continue
            destinatarios = sorted({c for u in candidatos_paso(db, paso) if (c := u.email or u.email_personal)})
            sede = p.usuario.sede
            cfg = correo.config_sede(db, sede)
            if not destinatarios or not cfg.get("CORREO_REMITENTE", "").strip():
                continue
            asunto, html_, texto = mensaje_paso(p, paso)
            notif = NotificacionCorreo(fecha=ahora(), evento="permiso_por_aprobar", permiso_id=p.id,
                                       sede_id=sede.id if sede else None, destinatarios=", ".join(destinatarios),
                                       asunto=asunto[:255])
            db.add(notif)
            db.commit()
            correo._registrar_y_enviar(db, notif, cfg, html_, texto)


def _tras_commit(session: Session):
    ids = session.info.pop("flujos_avisar", None)
    if not ids:
        return
    if SEGUNDO_PLANO:
        threading.Thread(target=avisar, args=(set(ids),), name="sip-flujos", daemon=True).start()
    else:
        avisar(set(ids))


def _tras_rollback(session: Session):
    session.info.pop("flujos_avisar", None)


def activar():
    event.listen(Session, "after_commit", _tras_commit)
    event.listen(Session, "after_rollback", _tras_rollback)
