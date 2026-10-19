"""Configuración de las listas de SharePoint de la sede activa (GH, Gerencia GH y super administrador)."""
import json
import threading
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import sharepoint
from ..database import get_db
from ..models import EnvioSharePoint, ListaSharePoint, Sede, Usuario
from ..security import ahora, require_admin
from ..sedes import Alcance, alcance, sede_principal

router = APIRouter(prefix="/api/sharepoint", tags=["sharepoint"])


class ConectarIn(BaseModel):
    url: str


class GuardarIn(BaseModel):
    activo: bool
    mapeo: dict[str, str]
    valores: dict[str, dict[str, str]] = {}
    # Aprobación en Teams (Power Automate)
    aprobacion_teams: bool = False
    col_decision: str | None = None
    val_aprobado: str | None = None
    val_rechazado: str | None = None
    col_comentario: str | None = None
    col_respondio: str | None = None
    cuenta_flujo: str | None = None


class ExistentesIn(BaseModel):
    desde: date


def _sede(db: Session, alc: Alcance) -> Sede:
    sid = alc.defecto or sede_principal(db).id
    alc.exigir(sid)
    return db.get(Sede, sid)


def _tipo(tipo: str) -> str:
    if tipo not in sharepoint.TIPOS:
        raise HTTPException(404, "Tipo de lista no válido")
    return tipo


def _lista(db: Session, sede: Sede, tipo: str) -> ListaSharePoint | None:
    return db.scalar(select(ListaSharePoint).where(ListaSharePoint.sede_id == sede.id, ListaSharePoint.tipo == tipo))


def _estado(db: Session, sede: Sede, tipo: str) -> dict:
    campos = [{"clave": k, "etiqueta": v[0], "tipo": v[1], "valores": v[2]} for k, v in sharepoint.CAMPOS[tipo].items()]
    l = _lista(db, sede, tipo)
    if not l:
        return {"tipo": tipo, "conectada": False, "campos": campos}
    cuentas = dict(db.execute(select(EnvioSharePoint.estado, func.count()).where(EnvioSharePoint.lista_id == l.id)
                              .group_by(EnvioSharePoint.estado)).all())
    errores = db.scalars(select(EnvioSharePoint).where(EnvioSharePoint.lista_id == l.id, EnvioSharePoint.estado == "error")
                         .order_by(EnvioSharePoint.actualizado.desc()).limit(10)).all()
    return {
        "tipo": tipo, "conectada": True, "campos": campos, "url": l.url, "sitio_nombre": l.sitio_nombre,
        "lista_nombre": l.lista_nombre, "columnas": json.loads(l.columnas or "[]"), "mapeo": json.loads(l.mapeo or "{}"),
        "valores": json.loads(l.valores or "{}"), "activo": l.activo, "actualizado": l.actualizado,
        "cuentas": {"enviado": cuentas.get("enviado", 0), "pendiente": cuentas.get("pendiente", 0),
                    "error": cuentas.get("error", 0)},
        "errores": [{"folio": f"{'VAC' if tipo == 'vacaciones' else 'PER'}-{e.registro_id}", "error": e.error,
                     "intentos": e.intentos, "fecha": e.actualizado} for e in errores],
        "teams": {"activo": l.aprobacion_teams, "col_decision": l.col_decision,
                  "val_aprobado": l.val_aprobado or sharepoint.APROBADO_DEF, "val_rechazado": l.val_rechazado or sharepoint.RECHAZADO_DEF,
                  "col_comentario": l.col_comentario, "col_respondio": l.col_respondio, "cuenta_flujo": l.cuenta_flujo},
        "notas_teams": [{"folio": f"{'VAC' if tipo == 'vacaciones' else 'PER'}-{e.registro_id}", "nota": e.decision_nota}
                        for e in db.scalars(select(EnvioSharePoint).where(EnvioSharePoint.lista_id == l.id,
                                                                          EnvioSharePoint.decision_nota.is_not(None))
                                            .order_by(EnvioSharePoint.id.desc()).limit(10))],
    }


def _procesar(lista_id: int):
    if sharepoint.SEGUNDO_PLANO:
        threading.Thread(target=sharepoint.procesar_pendientes, args=(lista_id,), daemon=True).start()


@router.get("")
def obtener(db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    sede = _sede(db, alc)
    return {"sede_nombre": sede.nombre, "listas": {t: _estado(db, sede, t) for t in sharepoint.TIPOS}}


@router.put("/{tipo}/conectar")
def conectar(tipo: str, data: ConectarIn, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
             alc: Alcance = Depends(alcance)):
    """Lee el sitio, la lista y sus columnas; sugiere el mapeo si la lista es nueva o cambió."""
    tipo, sede = _tipo(tipo), _sede(db, alc)
    try:
        info = sharepoint.conectar(data.url)
    except sharepoint.ErrorSharePoint as e:
        raise HTTPException(422, e.mensaje)
    l = _lista(db, sede, tipo)
    otra_lista = not l or l.lista_id != info["lista_id"]
    if not l:
        l = ListaSharePoint(sede_id=sede.id, tipo=tipo, activo=False)
        db.add(l)
    elif otra_lista:  # otra lista: los elementos ya enviados pertenecen a la anterior
        db.query(EnvioSharePoint).filter(EnvioSharePoint.lista_id == l.id).delete()
        l.activo = False
    l.url, l.sitio_id, l.sitio_nombre = data.url.strip(), info["sitio_id"], info["sitio_nombre"]
    l.lista_id, l.lista_nombre, l.columnas = info["lista_id"], info["lista_nombre"], json.dumps(info["columnas"], ensure_ascii=False)
    nombres = {c["nombre"] for c in info["columnas"]}
    mapeo = {k: v for k, v in json.loads(l.mapeo or "{}").items() if k in nombres} if not otra_lista else {}
    if not mapeo:
        mapeo = sharepoint.sugerir_mapeo(tipo, info["columnas"])
    l.mapeo = json.dumps(mapeo, ensure_ascii=False)
    valores = json.loads(l.valores or "{}") if not otra_lista else {}
    l.valores = json.dumps({**sharepoint.sugerir_valores(tipo, info["columnas"], mapeo), **valores}, ensure_ascii=False)
    l.actualizado, l.actualizado_por_id = ahora(), admin.id
    db.commit()
    return _estado(db, sede, tipo)


@router.put("/{tipo}")
def guardar(tipo: str, data: GuardarIn, db: Session = Depends(get_db), admin: Usuario = Depends(require_admin),
            alc: Alcance = Depends(alcance)):
    tipo, sede = _tipo(tipo), _sede(db, alc)
    l = _lista(db, sede, tipo)
    if not l:
        raise HTTPException(404, "Primero conecta la lista con su URL.")
    columnas = {c["nombre"]: c for c in json.loads(l.columnas or "[]")}
    mapeo = {k: v for k, v in data.mapeo.items() if v}
    for col, campo in mapeo.items():
        if col not in columnas or campo not in sharepoint.CAMPOS[tipo]:
            raise HTTPException(422, f"Columna o dato no válido: {col}")
        if not columnas[col]["compatible"]:
            raise HTTPException(422, f"La columna «{columnas[col]['titulo']}» es de tipo {columnas[col]['tipo']} y no se "
                                     "puede llenar desde SIP-O; usa una columna de texto.")
    if data.activo:
        faltan = [c["titulo"] for c in columnas.values() if c["requerida"] and c["compatible"] and c["nombre"] not in mapeo]
        if faltan:
            raise HTTPException(422, f"Asigna un dato a las columnas obligatorias: {', '.join(faltan)}.")
        if not mapeo:
            raise HTTPException(422, "Asigna al menos un dato a una columna.")
    _validar_teams(data, columnas, mapeo)
    l.mapeo = json.dumps(mapeo, ensure_ascii=False)
    l.valores = json.dumps({k: {a: b for a, b in v.items() if b} for k, v in data.valores.items() if k in mapeo},
                           ensure_ascii=False)
    l.activo, l.actualizado, l.actualizado_por_id = data.activo, ahora(), admin.id
    l.aprobacion_teams = data.aprobacion_teams
    l.col_decision, l.col_comentario, l.col_respondio = data.col_decision or None, data.col_comentario or None, data.col_respondio or None
    l.val_aprobado = (data.val_aprobado or "").strip() or None
    l.val_rechazado = (data.val_rechazado or "").strip() or None
    l.cuenta_flujo = (data.cuenta_flujo or "").strip().lower() or None
    db.commit()
    return _estado(db, sede, tipo)


def _validar_teams(data: GuardarIn, columnas: dict, mapeo: dict):
    if not data.aprobacion_teams:
        return
    if not data.activo:
        raise HTTPException(422, "Para aprobar en Teams, activa también el envío de solicitudes a la lista.")
    if not data.col_decision:
        raise HTTPException(422, "Elige la columna donde el flujo escribirá la decisión (Approve / Reject).")
    for etiqueta, col in (("decisión", data.col_decision), ("comentarios", data.col_comentario), ("quién respondió", data.col_respondio)):
        if not col:
            continue
        c = columnas.get(col)
        if not c or c["tipo"] not in ("text", "choice"):
            raise HTTPException(422, f"La columna de {etiqueta} debe ser una columna de texto u opción de la lista.")
        if col in mapeo:
            raise HTTPException(422, f"La columna «{c['titulo']}» la escribe el flujo: quítale el dato de SIP-O.")
    if len({data.col_decision, data.col_comentario, data.col_respondio} - {None, ""}) < \
            len([x for x in (data.col_decision, data.col_comentario, data.col_respondio) if x]):
        raise HTTPException(422, "Usa una columna distinta para la decisión, los comentarios y quién respondió.")
    falta = [e for k, e in (("correo_jefe", "Correo del jefe / aprobador"), ("estado", "Estado")) if k not in mapeo.values()]
    if falta:
        raise HTTPException(422, f"Para aprobar en Teams, envía a la lista estos datos: {', '.join(falta)} "
                                 "(el flujo los usa para saber a quién pedir la aprobación y si está pendiente).")


@router.post("/{tipo}/existentes")
def enviar_existentes(tipo: str, data: ExistentesIn, db: Session = Depends(get_db), _=Depends(require_admin),
                      alc: Alcance = Depends(alcance)):
    """Envía también las solicitudes que ya existían (desde una fecha); las ya enviadas no se duplican."""
    tipo, sede = _tipo(tipo), _sede(db, alc)
    l = _lista(db, sede, tipo)
    if not l or not l.activo:
        raise HTTPException(422, "Activa primero el envío a la lista.")
    n = sharepoint.encolar_existentes(db, l, data.desde)
    db.commit()
    _procesar(l.id)
    return {"encolados": n, **_estado(db, sede, tipo)}


@router.post("/{tipo}/reintentar")
def reintentar(tipo: str, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    tipo, sede = _tipo(tipo), _sede(db, alc)
    l = _lista(db, sede, tipo)
    if not l:
        raise HTTPException(404, "Lista no conectada")
    db.query(EnvioSharePoint).filter(EnvioSharePoint.lista_id == l.id, EnvioSharePoint.estado == "error") \
        .update({"estado": "pendiente", "intentos": 0})
    db.commit()
    _procesar(l.id)
    return _estado(db, sede, tipo)


@router.delete("/{tipo}")
def desconectar(tipo: str, db: Session = Depends(get_db), _=Depends(require_admin), alc: Alcance = Depends(alcance)):
    """Deja de enviar a la lista. No borra nada en SharePoint."""
    tipo, sede = _tipo(tipo), _sede(db, alc)
    l = _lista(db, sede, tipo)
    if l:
        db.query(EnvioSharePoint).filter(EnvioSharePoint.lista_id == l.id).delete()
        db.delete(l)
        db.commit()
    return _estado(db, sede, tipo)
