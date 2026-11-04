"""Cadenas de aprobación personalizadas por tipo de permiso.

- GH arma por sede flujos con nombre (p. ej. "Jefe → TI → GH") y asigna uno a cada tipo de permiso.
- Al enviarse un permiso, los pasos del flujo se copian al permiso (solicitud_pasos) y se resuelve quién aprueba
  cada uno; cambiar la configuración después no afecta lo que ya está en curso.
- Aprobar cierra el paso actual y activa el siguiente; al aprobarse el último, el permiso queda validado.
  Rechazar en cualquier paso termina la solicitud. En los pasos de grupo (GH, TI) basta con que apruebe uno.
- GH de la sede siempre puede resolver directamente (los pasos que faltaban quedan omitidos).
- Sin flujo asignado (o con los permisos registrados en caseta) se sigue la regla de la sede: jefe, o jefe y después GH.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, object_session

from .models import (
    VALIDADO, FlujoAprobacion, PasoSolicitud, Permiso, TipoPermisoSede, Usuario, es_admin,
)
from .sedes import admin_permite

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
    """En esta fase Teams solo resuelve el primer paso de la cadena (y solo si ese paso va a Teams)."""
    pasos = getattr(permiso, "pasos", None)
    if not pasos:
        return True
    paso = actual(permiso)
    primero = next((p for p in pasos if p.estado != OMITIDO), None)
    return paso is not None and paso is primero and paso.teams


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
    legado = and_(Permiso.aprobador_id == user.id, sin_cadena)
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
