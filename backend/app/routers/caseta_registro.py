"""Caseta (app de Android): registro de entradas y salidas por QR, equipos de cómputo por código de barras y avisos.

- Cada empleado tiene un QR firmado (HMAC con la clave del servidor) que muestra en SIP-O o en su gafete.
  Al escanearlo, caseta registra su salida o su entrada y SIP-O valida si tiene un permiso por horas aprobado
  para ese momento. Siempre se guarda el movimiento, con o sin permiso, para que quede constancia.
- Los equipos de cómputo se registran por su código de barras (etiqueta de inventario o número de serie): salida o
  entrada, quién lo lleva y si tiene un permiso «Salida de equipo» aprobado para hoy.
- /avisos devuelve los permisos por horas aprobados de hoy y de los próximos días; la app los compara con los que ya
  conoce para avisar de los nuevos (sin servicios externos de notificaciones).
"""
import hashlib
import hmac
import re
import unicodedata
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import tipos_permiso
from ..config import settings
from ..database import get_db
from ..models import TIPO_RETARDO, VALIDADO, MovimientoCaseta, Permiso, Usuario, es_admin
from ..security import auditar, get_current_user
from ..sedes import ahora_en
from .caseta import _persona, _sedes, require_caseta

router = APIRouter(prefix="/api/caseta", tags=["caseta"])

PREFIJO_QR = "SIPO-E1"
TOLERANCIA = timedelta(minutes=15)   # margen antes de la salida autorizada y después de la entrada autorizada
DOBLE_ESCANEO = timedelta(seconds=60)
DIAS_AVISOS = 7


# ---------------- QR del empleado ----------------

def _firma(usuario_id: int) -> str:
    llave = hashlib.sha256(f"sip-qr:{settings.secret_key}".encode()).digest()
    return hmac.new(llave, f"{PREFIJO_QR}.{usuario_id}".encode(), hashlib.sha256).hexdigest()[:20]


def codigo_qr(usuario_id: int) -> str:
    return f"{PREFIJO_QR}.{usuario_id}.{_firma(usuario_id)}"


def leer_qr(codigo: str) -> int | None:
    partes = (codigo or "").strip().split(".")
    if len(partes) != 3 or partes[0] != PREFIJO_QR or not partes[1].isdigit():
        return None
    uid = int(partes[1])
    return uid if hmac.compare_digest(partes[2], _firma(uid)) else None


@router.get("/qr/mio")
def mi_qr(user: Usuario = Depends(get_current_user)):
    """QR personal para registrar entradas y salidas en caseta."""
    return {"codigo": codigo_qr(user.id), "nombre": user.nombre, "numero_empleado": user.numero_empleado}


@router.get("/qr/{usuario_id}")
def qr_de(usuario_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """QR de un empleado para imprimir su gafete (solo GH de su sede)."""
    if not es_admin(user):
        raise HTTPException(403, "Solo GH puede ver el QR de otros empleados.")
    u = db.get(Usuario, usuario_id)
    if not u or u.sede_id not in _sedes(db, user):
        raise HTTPException(404, "Empleado no encontrado")
    return {"codigo": codigo_qr(u.id), "nombre": u.nombre, "numero_empleado": u.numero_empleado}


# ---------------- Utilidades ----------------

def hora_evento(p: Permiso) -> time:
    """Hora a la que caseta ve el movimiento: la entrada en una llegada tarde; la salida en los demás."""
    return p.hora_fin if p.tipo == TIPO_RETARDO else p.hora_inicio


def _es_salida(p: Permiso) -> bool:
    return p.tipo != TIPO_RETARDO


def _hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def _sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def _usuarios_de(db: Session, user: Usuario):
    return select(Usuario.id).where(Usuario.sede_id.in_([x for x in _sedes(db, user) if x is not None] or [-1]))


def _permisos_por_horas(db: Session, usuario: Usuario, dia: date) -> list[Permiso]:
    q = select(Permiso).where(Permiso.usuario_id == usuario.id, Permiso.estado == VALIDADO, Permiso.fecha <= dia,
                              func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= dia)
    lista = [p for p in db.scalars(q) if not tipos_permiso.por_dias(db, usuario.sede_id, p.tipo)]
    return sorted(lista, key=hora_evento)


def _fila_mov(db: Session, m: MovimientoCaseta) -> dict:
    p = m.permiso
    return {"id": m.id, "clase": m.clase, "tipo": m.tipo, "fecha": m.fecha.isoformat(), "hora": _hhmm(m.hora),
            "con_permiso": m.con_permiso, "detalle": m.detalle, "equipo_codigo": m.equipo_codigo,
            "persona": _persona(m.usuario) if m.usuario else None,
            "permiso": {"id": p.id, "tipo": p.tipo, "tipo_nombre": tipos_permiso.nombre(db, m.usuario.sede_id if m.usuario else None, p.tipo),
                        "hora_inicio": _hhmm(p.hora_inicio), "hora_fin": _hhmm(p.hora_fin)} if p else None,
            "registrado_por": m.registrado_por.nombre if m.registrado_por else None}


def _guardar(db: Session, user: Usuario, **datos) -> MovimientoCaseta:
    m = MovimientoCaseta(registrado_por_id=user.id, **datos)
    db.add(m)
    db.flush()
    auditar(db, f"caseta_{datos['clase']}_{datos['tipo']}", usuario_id=datos.get("usuario_id"), actor_id=user.id,
            detalle=f"{'con' if datos.get('con_permiso') else 'SIN'} permiso"
                    + (f" · equipo {datos['equipo_codigo']}" if datos.get("equipo_codigo") else ""))
    db.commit()
    db.refresh(m)
    return m


def _empleado_visible(db: Session, user: Usuario, usuario_id: int) -> Usuario:
    u = db.get(Usuario, usuario_id)
    if not u or u.sede_id not in _sedes(db, user):
        raise HTTPException(404, "La persona no es de tu sede.")
    if not u.activo:
        raise HTTPException(422, f"{u.nombre} está dado de baja en SIP-O.")
    return u


# ---------------- Escaneo de personas ----------------

@router.get("/persona-qr")
def persona_qr(codigo: str, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Identifica a la persona de un QR sin registrar movimiento (p. ej. quién lleva un equipo)."""
    uid = leer_qr(codigo)
    if uid is None:
        raise HTTPException(422, "El código no es un QR de empleado de SIP-O.")
    return _persona(_empleado_visible(db, user, uid))


class EscaneoIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=200)
    tipo: str | None = Field(default=None, pattern="^(entrada|salida)$")  # para corregir lo que propone SIP-O


def _decidir(db: Session, u: Usuario, ahora_local: datetime, tipo: str | None) -> tuple[str, Permiso | None, bool, str]:
    """Qué movimiento es (si caseta no lo eligió), con qué permiso y si es válido. Devuelve (tipo, permiso, válido, texto)."""
    dia, hora = ahora_local.date(), ahora_local.time()
    permisos = _permisos_por_horas(db, u, dia)
    movs = list(db.scalars(select(MovimientoCaseta).where(
        MovimientoCaseta.clase == "persona", MovimientoCaseta.usuario_id == u.id, MovimientoCaseta.fecha == dia)
        .order_by(MovimientoCaseta.id)))
    usados = {m.permiso_id for m in movs if m.permiso_id and m.con_permiso}
    ultimo = movs[-1] if movs else None
    salidas = [p for p in permisos if _es_salida(p) and p.id not in usados]
    entradas = [p for p in permisos if not _es_salida(p) and p.id not in usados]

    if tipo is None:
        if ultimo and ultimo.tipo == "salida":
            tipo = "entrada"
        elif entradas and not salidas:
            tipo = "entrada"
        else:
            tipo = "salida"

    def dt(t: time) -> datetime:
        return datetime.combine(dia, t)

    if tipo == "salida":
        if not salidas:
            return tipo, None, False, "No tiene un permiso de salida aprobado para hoy."
        # El permiso cuya hora de salida está más cerca de ahora
        p = min(salidas, key=lambda x: abs(dt(x.hora_inicio) - ahora_local))
        if ahora_local < dt(p.hora_inicio) - TOLERANCIA:
            return tipo, p, False, f"Su permiso es para salir a las {_hhmm(p.hora_inicio)}; todavía no es hora."
        if p.tipo == "salida_intermedia":
            return tipo, p, True, f"Salida autorizada. Debe regresar a las {_hhmm(p.hora_fin)}."
        return tipo, p, True, "Salida autorizada."

    # Entrada: regreso de una salida durante la jornada o llegada tarde con permiso
    if ultimo and ultimo.tipo == "salida" and ultimo.permiso_id:
        p = ultimo.permiso
        tarde = p and p.tipo == "salida_intermedia" and ahora_local > dt(p.hora_fin) + TOLERANCIA
        return tipo, p, True, (f"Regreso registrado, después de la hora autorizada ({_hhmm(p.hora_fin)})." if tarde
                               else "Regreso registrado.")
    if entradas:
        p = entradas[0]
        if ahora_local > dt(p.hora_fin) + TOLERANCIA:
            return tipo, p, False, (f"Su llegada tarde estaba autorizada hasta las {_hhmm(p.hora_fin)}; "
                                    "llegó después. Solicita su ingreso por retardo.")
        return tipo, p, True, f"Llegada tarde autorizada (entrada a las {_hhmm(p.hora_fin)})."
    return tipo, None, False, "No tiene un permiso aprobado para entrar a esta hora. Solicita su ingreso por retardo."


@router.post("/escanear", status_code=201)
def escanear(data: EscaneoIn, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    uid = leer_qr(data.codigo)
    if uid is None:
        raise HTTPException(422, "El código no es un QR de empleado de SIP-O.")
    u = _empleado_visible(db, user, uid)
    ahora_local = ahora_en(u.sede).replace(second=0, microsecond=0)
    # Doble escaneo seguido: se devuelve el mismo registro
    previo = db.scalar(select(MovimientoCaseta).where(
        MovimientoCaseta.clase == "persona", MovimientoCaseta.usuario_id == u.id).order_by(MovimientoCaseta.id.desc()))
    if (previo and previo.fecha == ahora_local.date() and (data.tipo in (None, previo.tipo))
            and abs(datetime.combine(previo.fecha, previo.hora) - ahora_local) <= DOBLE_ESCANEO):
        return {**_fila_mov(db, previo), "mensaje": previo.detalle, "repetido": True}
    tipo, permiso, valido, texto = _decidir(db, u, ahora_local, data.tipo)
    m = _guardar(db, user, sede_id=u.sede_id, clase="persona", tipo=tipo, usuario_id=u.id,
                 permiso_id=permiso.id if permiso else None, con_permiso=valido, detalle=texto,
                 fecha=ahora_local.date(), hora=ahora_local.time())
    return {**_fila_mov(db, m), "mensaje": texto, "repetido": False}


# ---------------- Equipos de cómputo ----------------

class EquipoIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=120)
    tipo: str = Field(pattern="^(entrada|salida)$")
    usuario_id: int | None = None
    nota: str | None = Field(default=None, max_length=300)


def _es_tipo_equipo(db: Session, sede_id: int | None, clave: str) -> bool:
    return "equipo" in _sin_acentos(clave) or "equipo" in _sin_acentos(tipos_permiso.nombre(db, sede_id, clave))


def _limpiar_codigo(c: str) -> str:
    return re.sub(r"\s+", "", c or "").upper()


@router.get("/equipos/{codigo}")
def equipo(codigo: str, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Último movimiento del equipo: sugiere si ahora entra o sale y quién lo llevaba."""
    cod = _limpiar_codigo(codigo)
    ult = db.scalar(select(MovimientoCaseta).where(MovimientoCaseta.clase == "equipo", MovimientoCaseta.equipo_codigo == cod,
                                                   MovimientoCaseta.sede_id.in_([x for x in _sedes(db, user) if x is not None] or [-1]))
                    .order_by(MovimientoCaseta.id.desc()))
    return {"codigo": cod, "ultimo": _fila_mov(db, ult) if ult else None,
            "sugerido": "entrada" if ult and ult.tipo == "salida" else "salida"}


@router.post("/equipos", status_code=201)
def registrar_equipo(data: EquipoIn, db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    cod = _limpiar_codigo(data.codigo)
    if not cod:
        raise HTTPException(422, "Escanea o escribe el código del equipo.")
    u = _empleado_visible(db, user, data.usuario_id) if data.usuario_id else None
    sede = u.sede if u else user.sede
    ahora_local = ahora_en(sede).replace(second=0, microsecond=0)
    dia = ahora_local.date()
    permiso, valido = None, False
    if u:
        q = select(Permiso).where(Permiso.usuario_id == u.id, Permiso.estado == VALIDADO, Permiso.fecha <= dia,
                                  func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= dia)
        permiso = next((p for p in db.scalars(q) if _es_tipo_equipo(db, u.sede_id, p.tipo)), None)
        valido = permiso is not None
    if data.tipo == "entrada":
        texto = "Regreso del equipo registrado."
        valido = True  # el regreso no requiere permiso
    elif not u:
        texto = "Salida sin indicar quién lleva el equipo."
    elif valido:
        texto = f"Salida autorizada: {u.nombre} tiene permiso «{tipos_permiso.nombre(db, u.sede_id, permiso.tipo)}» aprobado."
    else:
        texto = f"{u.nombre} NO tiene un permiso de salida de equipo aprobado para hoy."
    if data.nota:
        texto += f" Nota: {data.nota.strip()}"
    m = _guardar(db, user, sede_id=sede.id if sede else None, clase="equipo", tipo=data.tipo, usuario_id=u.id if u else None,
                 permiso_id=permiso.id if permiso else None, con_permiso=valido, detalle=texto, equipo_codigo=cod,
                 fecha=dia, hora=ahora_local.time())
    return {**_fila_mov(db, m), "mensaje": texto}


# ---------------- Bitácora del día y avisos ----------------

@router.get("/movimientos")
def movimientos(fecha: date | None = None, clase: str | None = None, db: Session = Depends(get_db),
                user: Usuario = Depends(require_caseta)):
    dia = fecha or ahora_en(user.sede).date()
    q = select(MovimientoCaseta).where(MovimientoCaseta.fecha == dia,
                                       MovimientoCaseta.sede_id.in_([x for x in _sedes(db, user) if x is not None] or [-1]))
    if clase in ("persona", "equipo"):
        q = q.where(MovimientoCaseta.clase == clase)
    return [_fila_mov(db, m) for m in db.scalars(q.order_by(MovimientoCaseta.id.desc()).limit(300))]


@router.get("/avisos")
def avisos(db: Session = Depends(get_db), user: Usuario = Depends(require_caseta)):
    """Permisos por horas aprobados de hoy y de los próximos días; primero los de hoy, por la hora del movimiento."""
    hoy = ahora_en(user.sede).date()
    hasta = hoy + timedelta(days=DIAS_AVISOS)
    q = select(Permiso).where(Permiso.estado == VALIDADO, Permiso.usuario_id.in_(_usuarios_de(db, user)),
                              Permiso.fecha <= hasta, func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= hoy)
    lista = []
    for p in db.scalars(q):
        if tipos_permiso.por_dias(db, p.usuario.sede_id, p.tipo):
            continue
        es_hoy = p.fecha <= hoy
        lista.append({"id": p.id, "nombre": p.usuario.nombre, "numero_empleado": p.usuario.numero_empleado,
                      "tipo": p.tipo, "tipo_nombre": tipos_permiso.nombre(db, p.usuario.sede_id, p.tipo),
                      "fecha": max(p.fecha, hoy).isoformat(), "es_hoy": es_hoy, "hora": _hhmm(hora_evento(p)),
                      "hora_inicio": _hhmm(p.hora_inicio), "hora_fin": _hhmm(p.hora_fin)})
    lista.sort(key=lambda a: (not a["es_hoy"], a["fecha"], a["hora"] or "", a["nombre"]))
    return {"hoy": hoy.isoformat(), "avisos": lista}
