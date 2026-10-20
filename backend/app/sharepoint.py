"""Envío de las solicitudes de vacaciones y permisos a listas de SharePoint (Microsoft Graph).

- Cada sede puede conectar una lista para vacaciones y otra para permisos pegando su URL.
- El administrador elige qué dato de SIP-O va en cada columna de la lista (mapeo) y, en columnas de opción,
  qué opción corresponde a cada estado o tipo.
- Una solicitud se envía cuando deja de ser borrador; después, cada cambio (validación, rechazo, cancelación,
  edición) actualiza el mismo elemento de la lista. Si se elimina en SIP-O, el elemento no se borra: su estado
  cambia a "Eliminado" (si hay una columna de estado mapeada).
- El envío va en segundo plano con cola y reintentos (tabla sharepoint_envios): si Microsoft no responde,
  la solicitud en SIP-O no falla y se reintenta cada 10 minutos.
- Requiere el permiso de aplicación Sites.ReadWrite.All (o Sites.Selected con acceso al sitio) en Graph.
"""
import json
import logging
import re
import threading
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, unquote, urlparse
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session, object_session

from . import microsoft
from .config import settings
from .security import ahora as _ahora
from .models import (
    BORRADOR, PERMISO_CONSULTA_MEDICA, EnvioSharePoint, ListaSharePoint, Permiso, Sede, SolicitudVacaciones, Usuario,
)

log = logging.getLogger("sip.sharepoint")
TIPOS = ("vacaciones", "permisos")
SEGUNDO_PLANO = True  # las pruebas lo apagan y llaman a procesar_pendientes() directamente
MAX_INTENTOS = 8

ESTADOS = {"borrador": "Borrador", "solicitado": "Solicitado", "validado": "Validado", "rechazado": "Rechazado",
           "cancelado": "Cancelado", "eliminado": "Eliminado"}
PERMISOS = {"llegada_tarde": "Llegada tarde", "salida_temprana": "Salida temprana",
            "salida_intermedia": "Salida durante la jornada", "home_office": "Home office"}
NOMINA = {"con_goce": "Con goce de sueldo", "sin_goce": "Sin goce de sueldo", "reposicion": "Reposición de tiempo"}

# Datos de SIP-O que se pueden enviar: clave -> (etiqueta, tipo, valores posibles para columnas de opción)
_COMUNES_INI = {
    "empleado": ("Empleado", "texto", None), "numero_empleado": ("No. de nómina", "texto", None),
    "correo": ("Correo del empleado", "texto", None), "puesto": ("Puesto", "texto", None),
    "departamento": ("Departamento", "texto", None), "sede": ("Sede", "texto", None),
    "jefe": ("Jefe / aprobador", "texto", None), "correo_jefe": ("Correo del jefe / aprobador", "texto", None),
}
_COMUNES_FIN = {
    "estado": ("Estado", "texto", ESTADOS), "motivo_rechazo": ("Motivo de rechazo", "texto", None),
    "fecha_solicitud": ("Fecha de solicitud", "fechahora", None), "revisado_por": ("Revisado por", "texto", None),
    "fecha_revision": ("Fecha de revisión", "fechahora", None), "enlace": ("Enlace a SIP-O", "texto", None),
}
CAMPOS = {
    "vacaciones": {
        "folio": ("Folio (VAC-123)", "texto", None), **_COMUNES_INI,
        "fecha_inicio": ("Primer día", "fecha", None), "fecha_fin": ("Último día", "fecha", None),
        "dias": ("Días hábiles", "numero", None), "horas": ("Horas", "numero", None),
        "periodo": ("Periodo vacacional", "texto", None), "fecha_ingreso": ("Fecha de ingreso", "fecha", None),
        "dias_periodo": ("Días generados en el periodo", "numero", None),
        "saldo_periodo": ("Saldo de días del periodo (después de la solicitud)", "numero", None),
        "comentario": ("Comentario", "texto", None), **_COMUNES_FIN,
    },
    "permisos": {
        "folio": ("Folio (PER-123)", "texto", None), **_COMUNES_INI,
        "tipo": ("Tipo de permiso", "texto", PERMISOS), "fecha": ("Fecha", "fecha", None),
        "fecha_fin": ("Último día (home office)", "fecha", None), "hora_inicio": ("Hora de inicio", "texto", None),
        "hora_fin": ("Hora de fin", "texto", None),
        "fecha_hora_inicio": ("Fecha y hora de salida / inicio", "fechahora", None),
        "fecha_hora_fin": ("Fecha y hora de regreso / fin", "fechahora", None),
        "horas": ("Horas", "numero", None), "motivo": ("Motivo", "texto", None),
        "tipo_nomina": ("Tipo en nómina", "texto", NOMINA), "observaciones": ("Observaciones", "texto", None),
        **_COMUNES_FIN,
    },
}
# Sugerencias para el mapeo automático (nombre de columna normalizado -> campo)
SINONIMOS = {
    "title": "folio", "titulo": "folio", "folio": "folio", "empleado": "empleado", "nombre": "empleado",
    "colaborador": "empleado", "solicitante": "empleado", "nombredelempleado": "empleado", "nomina": "numero_empleado",
    "numerodeempleado": "numero_empleado", "noempleado": "numero_empleado", "numeroempleado": "numero_empleado",
    "nodenomina": "numero_empleado", "correo": "correo", "email": "correo", "puesto": "puesto",
    "departamento": "departamento", "area": "departamento", "sede": "sede", "ubicacion": "sede", "jefe": "jefe",
    "jefeinmediato": "jefe", "aprobador": "jefe", "correojefe": "correo_jefe", "correodeljefe": "correo_jefe",
    "emailjefe": "correo_jefe", "correoaprobador": "correo_jefe", "correodelaprobador": "correo_jefe", "fechainicio": "fecha_inicio", "fechadeinicio": "fecha_inicio",
    "desde": "fecha_inicio", "inicio": "fecha_inicio", "fechafin": "fecha_fin", "fechadefin": "fecha_fin",
    "fechatermino": "fecha_fin", "hasta": "fecha_fin", "fin": "fecha_fin", "dias": "dias", "diashabiles": "dias",
    "diassolicitados": "dias", "horas": "horas", "periodo": "periodo", "comentario": "comentario",
    "comentarios": "comentario", "estado": "estado", "estatus": "estado", "status": "estado", "tipo": "tipo",
    "tipodepermiso": "tipo", "fecha": "fecha", "horainicio": "hora_inicio", "horadeinicio": "hora_inicio",
    "horasalida": "hora_inicio", "horafin": "hora_fin", "horadefin": "hora_fin", "horaregreso": "hora_fin",
    "motivo": "motivo", "tiponomina": "tipo_nomina", "goce": "tipo_nomina", "observaciones": "observaciones",
    "motivoderechazo": "motivo_rechazo", "fechadesolicitud": "fecha_solicitud", "fechasolicitud": "fecha_solicitud",
    "revisadopor": "revisado_por", "aprobadopor": "revisado_por", "fechaderevision": "fecha_revision",
    "fechaaprobacion": "fecha_revision", "enlace": "enlace", "link": "enlace",
    "fechaingreso": "fecha_ingreso", "fechadeingreso": "fecha_ingreso", "ingreso": "fecha_ingreso",
    "diastotalesgeneradosenelperiodo": "dias_periodo", "diasgenerados": "dias_periodo", "diasdelperiodo": "dias_periodo",
    "saldodediasdelperiodoindicado": "saldo_periodo", "saldo": "saldo_periodo", "saldodedias": "saldo_periodo",
    "periodoalquecorrespondenlosdiasatomar": "periodo", "desdeprimerdiadevacaciones": "fecha_inicio",
    "hastaultimodiadevacaciones": "fecha_fin", "numerodediasadisfrutar": "dias", "diasadisfrutar": "dias",
    "numerodenomina": "numero_empleado", "fechadelpermiso": "fecha", "seleccionalaopcionquecorresponda": "tipo",
    "seleccionacomoseraconsideradoeltiempoennomina": "tipo_nomina", "fechayhoradesolicitud": "fecha_hora_inicio",
    "fechayhoradesalida": "fecha_hora_inicio", "fechayhoraderegreso": "fecha_hora_fin",
}
TIPOS_COLUMNA = ("text", "number", "currency", "dateTime", "choice", "boolean")


class ErrorSharePoint(Exception):
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


def normalizar(s: str) -> str:
    from .sedes import normalizar as n
    return re.sub(r"[^a-z0-9]", "", n(s or ""))


# ---------------- Graph ----------------
def _graph(metodo: str, ruta: str, cuerpo=None) -> httpx.Response:
    if not settings.microsoft_configurado and not settings.graph_configurado:
        raise ErrorSharePoint("Configura primero la conexión con Microsoft (Configuración → Conexión con Microsoft).")
    for intento in range(2):
        try:
            token = microsoft.token_aplicacion()
            with microsoft._cliente() as c:
                r = c.request(metodo, f"{settings.microsoft_graph_url}/{ruta}", json=cuerpo,
                              headers={"Authorization": f"Bearer {token}"})
        except microsoft.ErrorMicrosoft as e:
            raise ErrorSharePoint(e.mensaje)
        except httpx.HTTPError as e:
            raise ErrorSharePoint(f"No se pudo contactar a Microsoft ({type(e).__name__}).")
        if r.status_code not in (401, 403) or intento:
            break
        microsoft._token_app.update(valor=None, expira=0)  # el token en caché pudo ser anterior al permiso
    if r.status_code in (401, 403):
        roles = microsoft.roles_token(token)
        tiene = [x for x in roles if x.startswith("Sites.")]
        raise ErrorSharePoint(
            "Microsoft negó el acceso a la lista. La aplicación necesita el permiso de aplicación Sites.ReadWrite.All "
            "(o Sites.Selected con acceso de escritura a este sitio) con consentimiento de administrador."
            + (f" Permisos actuales: {', '.join(tiene)}." if tiene else "") + _detalle(r))
    return r


def _detalle(r: httpx.Response) -> str:
    try:
        e = r.json().get("error", {})
    except ValueError:
        return ""
    texto = str(e.get("message", ""))[:250]
    return f" Detalle de Microsoft: {texto}" if texto else ""


def analizar_url(url: str) -> tuple[str, str, str]:
    """(host, ruta del sitio, segmento de la lista) a partir de la URL de la lista."""
    u = urlparse((url or "").strip())
    if u.scheme != "https" or not u.netloc.lower().endswith(".sharepoint.com"):
        raise ErrorSharePoint("Pega la URL completa de la lista de SharePoint (https://<empresa>.sharepoint.com/...).")
    ruta = unquote(u.path)
    m = re.search(r"/lists/([^/]+)", ruta, re.IGNORECASE)
    if not m:
        raise ErrorSharePoint("La URL no parece de una lista: abre la lista en SharePoint y copia la dirección "
                              "(debe contener /Lists/).")
    return u.netloc.lower(), ruta[:m.start()].rstrip("/"), m.group(1)


def conectar(url: str) -> dict:
    """Busca el sitio y la lista y lee sus columnas."""
    host, ruta_sitio, segmento = analizar_url(url)
    r = _graph("GET", f"sites/{host}:{quote(ruta_sitio)}" if ruta_sitio else f"sites/{host}")
    if r.status_code == 404:
        raise ErrorSharePoint(f"No se encontró el sitio {host}{ruta_sitio}.")
    if r.status_code != 200:
        raise ErrorSharePoint(f"Microsoft respondió HTTP {r.status_code} al buscar el sitio." + _detalle(r))
    sitio = r.json()
    r = _graph("GET", f"sites/{sitio['id']}/lists?$select=id,displayName,webUrl&$top=500")
    if r.status_code != 200:
        raise ErrorSharePoint(f"Microsoft respondió HTTP {r.status_code} al leer las listas del sitio." + _detalle(r))
    listas = r.json().get("value", [])
    buscada = normalizar(segmento)
    lista = next((x for x in listas if normalizar(unquote(urlparse(x.get("webUrl", "")).path.rstrip("/").split("/")[-1])) == buscada), None) \
        or next((x for x in listas if normalizar(x.get("displayName", "")) == buscada), None)
    if not lista:
        raise ErrorSharePoint(f"No se encontró la lista «{segmento}» en el sitio {sitio.get('displayName') or ruta_sitio}.")
    r = _graph("GET", f"sites/{sitio['id']}/lists/{lista['id']}/columns")
    if r.status_code != 200:
        raise ErrorSharePoint(f"Microsoft respondió HTTP {r.status_code} al leer las columnas." + _detalle(r))
    return {"sitio_id": sitio["id"], "sitio_nombre": sitio.get("displayName"), "lista_id": lista["id"],
            "lista_nombre": lista.get("displayName"), "columnas": columnas_de(r.json().get("value", []))}


def columnas_de(valores: list[dict]) -> list[dict]:
    """Columnas editables de la lista con su tipo (las de persona, búsqueda o calculadas no se pueden llenar)."""
    res = []
    for c in valores:
        if c.get("readOnly") or c.get("hidden") or c.get("name") in ("ContentType", "Attachments", "_ColorTag", "ComplianceAssetId"):
            continue
        tipo = next((t for t in ("text", "number", "currency", "dateTime", "choice", "boolean", "personOrGroup", "lookup",
                                 "calculated", "hyperlinkOrPicture", "term") if t in c), "otro")
        res.append({
            "nombre": c["name"], "titulo": c.get("displayName") or c["name"], "tipo": tipo, "requerida": bool(c.get("required")),
            "opciones": (c.get("choice") or {}).get("choices") or [],
            "texto_libre": bool((c.get("choice") or {}).get("allowTextEntry")),
            "solo_fecha": (c.get("dateTime") or {}).get("format") == "dateOnly",
            "compatible": tipo in TIPOS_COLUMNA,
        })
    return res


def sugerir_mapeo(tipo: str, columnas: list[dict]) -> dict:
    campos = CAMPOS[tipo]
    mapeo, usados = {}, set()
    for c in columnas:
        if not c["compatible"]:
            continue
        clave = SINONIMOS.get(normalizar(c["titulo"])) or SINONIMOS.get(normalizar(c["nombre"]))
        if clave and clave in campos and clave not in usados:
            mapeo[c["nombre"]] = clave
            usados.add(clave)
    return mapeo


def sugerir_valores(tipo: str, columnas: list[dict], mapeo: dict) -> dict:
    """Para columnas de opción: la opción de la lista que corresponde a cada valor de SIP-O."""
    equivalentes = {"validado": ("aprobado", "aprobada", "autorizado", "autorizada", "validada"),
                    "solicitado": ("pendiente", "enviado", "enviada", "solicitada", "enrevision"),
                    "rechazado": ("rechazada", "denegado", "denegada", "noaprobado"),
                    "cancelado": ("cancelada",), "eliminado": ("eliminada", "cancelado", "cancelada")}
    res = {}
    for c in columnas:
        campo = mapeo.get(c["nombre"])
        posibles = CAMPOS[tipo].get(campo, (None, None, None))[2] if campo else None
        if c["tipo"] != "choice" or not posibles:
            continue
        opciones = {normalizar(o): o for o in c["opciones"]}
        res[c["nombre"]] = {}
        for k, etiqueta in posibles.items():
            elegido = opciones.get(normalizar(etiqueta)) or opciones.get(normalizar(k)) or next(
                (opciones[e] for e in equivalentes.get(k, ()) if e in opciones), None)
            if elegido:
                res[c["nombre"]][k] = elegido
    return res


# ---------------- Datos de cada solicitud ----------------
def _enlace(tipo: str, reg) -> str | None:
    base = settings.microsoft_frontend_url or (settings.cors_list[0] if settings.cors_list else "")
    return f"{base.rstrip('/')}/" if base else None


def _sesion(reg):
    try:
        return object_session(reg)
    except Exception:  # registros sueltos (p. ej. en pruebas)
        return None


def datos_registro(tipo: str, reg) -> dict:
    u: Usuario = reg.usuario
    comunes = {
        "empleado": u.nombre, "numero_empleado": u.numero_empleado, "correo": u.email or u.email_personal,
        "puesto": u.puesto, "departamento": getattr(reg, "departamento", None) or u.departamento,
        "sede": u.sede.nombre if u.sede else None, "jefe": reg.aprobador.nombre if reg.aprobador else None,
        "correo_jefe": (reg.aprobador.email or reg.aprobador.email_personal) if reg.aprobador else None,
        "estado": reg.estado, "motivo_rechazo": reg.motivo_rechazo, "fecha_solicitud": reg.creado,
        "revisado_por": reg.revisado_por.nombre if reg.revisado_por else None, "fecha_revision": reg.fecha_revision,
        "enlace": _enlace(tipo, reg),
    }
    if tipo == "vacaciones":
        saldo = None
        if reg.periodo is not None:
            from .services import saldo_periodo
            saldo = saldo_periodo(object_session(reg), reg.periodo)
        return {**comunes, "folio": f"VAC-{reg.id}", "fecha_ingreso": u.fecha_ingreso,
                "dias_periodo": round(saldo.dias_total, 2) if saldo else None,
                "saldo_periodo": round(saldo.dias_disponible, 2) if saldo else None, "fecha_inicio": reg.fecha_inicio, "fecha_fin": reg.fecha_fin,
                "dias": reg.dias_habiles, "horas": reg.horas, "periodo": reg.periodo.nombre if reg.periodo else None,
                "comentario": reg.comentario}
    tz = ZoneInfo(u.sede.zona_horaria) if u.sede and u.sede.zona_horaria else timezone.utc
    from . import tipos_permiso as _tp
    ho = _tp.por_dias(_sesion(reg), getattr(u, "sede_id", None), reg.tipo)
    ini = datetime.combine(reg.fecha, time(0) if ho or not reg.hora_inicio else reg.hora_inicio, tzinfo=tz)
    fin = datetime.combine(reg.fecha_fin or reg.fecha, time(0) if ho or not reg.hora_fin else reg.hora_fin, tzinfo=tz)
    from . import tipos_permiso as _tp
    tipo_valor = reg.tipo if reg.tipo in PERMISOS else _tp.nombre(_sesion(reg), getattr(u, "sede_id", None), reg.tipo)
    return {**comunes, "folio": f"PER-{reg.id}", "tipo": tipo_valor, "fecha": reg.fecha, "fecha_fin": reg.fecha_fin,
            "fecha_hora_inicio": ini, "fecha_hora_fin": fin,
            "hora_inicio": reg.hora_inicio.strftime("%H:%M") if reg.hora_inicio and reg.tipo != "home_office" else None,
            "hora_fin": reg.hora_fin.strftime("%H:%M") if reg.hora_fin and reg.tipo != "home_office" else None,
            "horas": reg.horas, "motivo": reg.motivo, "tipo_nomina": reg.tipo_nomina, "observaciones": reg.observaciones}


def _convertir(valor, columna: dict, campo: str, tipo: str, valores: dict, tz: ZoneInfo):
    if valor is None or valor == "":
        return None
    t = columna["tipo"]
    posibles = CAMPOS[tipo][campo][2]
    if posibles and t in ("choice", "text"):
        elegido = (valores.get(columna["nombre"]) or {}).get(valor)
        return elegido or posibles.get(valor, valor)
    if t in ("number", "currency"):
        try:
            return float(valor)
        except (TypeError, ValueError):
            return None
    if t == "boolean":
        return bool(valor)
    if t == "dateTime":
        if isinstance(valor, datetime):  # sin zona = hora local del servidor (creado, fecha de revisión)
            return valor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(valor, date):  # medianoche en la zona de la sede
            local = datetime.combine(valor, time(0), tzinfo=tz)
            return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return None
    if isinstance(valor, datetime):
        return valor.astimezone(tz).strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor)[:255] if t == "text" else str(valor)


def campos_lista(lista: ListaSharePoint, reg, eliminado: bool = False) -> dict:
    columnas = {c["nombre"]: c for c in json.loads(lista.columnas or "[]")}
    mapeo, valores = json.loads(lista.mapeo or "{}"), json.loads(lista.valores or "{}")
    sede = lista.sede
    tz = ZoneInfo(sede.zona_horaria) if sede and sede.zona_horaria else timezone.utc
    if eliminado:
        return {n: _convertir("eliminado", columnas[n], c, lista.tipo, valores, tz)
                for n, c in mapeo.items() if c == "estado" and n in columnas}
    datos = datos_registro(lista.tipo, reg)
    res = {}
    for nombre, campo in mapeo.items():
        if nombre in columnas and campo in CAMPOS[lista.tipo]:
            res[nombre] = _convertir(datos.get(campo), columnas[nombre], campo, lista.tipo, valores, tz)
    return res


# ---------------- Cola ----------------
def _modelo(tipo: str):
    return SolicitudVacaciones if tipo == "vacaciones" else Permiso


def _encolar(session: Session, _ctx):
    """Tras cada flush: pone en cola las solicitudes que cambiaron, si su sede tiene una lista activa."""
    objs = []
    for lista_objs, eliminado in ((session.new, False), (session.dirty, False), (session.deleted, True)):
        for o in lista_objs:
            if isinstance(o, SolicitudVacaciones):
                objs.append((o, "vacaciones", eliminado))
            elif isinstance(o, Permiso) and o.tipo != PERMISO_CONSULTA_MEDICA:
                objs.append((o, "permisos", eliminado))
    if not objs:
        return
    con = session.connection()
    L, E, U = ListaSharePoint.__table__, EnvioSharePoint.__table__, Usuario.__table__
    activas = {(r.sede_id, r.tipo): r.id for r in con.execute(select(L.c.id, L.c.sede_id, L.c.tipo).where(L.c.activo))}
    if not activas:
        return
    ahora = _ahora()
    for o, tipo, eliminado in objs:
        if o in session.dirty and not session.is_modified(o, include_collections=False):
            continue
        sede = con.execute(select(U.c.sede_id).where(U.c.id == o.usuario_id)).scalar()
        lid = activas.get((sede, tipo))
        if not lid:
            continue
        previo = con.execute(select(E.c.id).where(E.c.lista_id == lid, E.c.registro_id == o.id)).scalar()
        if previo:
            con.execute(update(E).where(E.c.id == previo).values(estado="pendiente", intentos=0, eliminado=eliminado,
                                                                error=None, actualizado=ahora))
        elif not eliminado and o.estado != BORRADOR:
            con.execute(E.insert().values(lista_id=lid, registro_id=o.id, estado="pendiente", intentos=0,
                                          eliminado=False, actualizado=ahora))
        else:
            continue
        session.info["sharepoint_cola"] = True


def _tras_commit(session: Session):
    if session.info.pop("sharepoint_cola", False) and SEGUNDO_PLANO:
        threading.Thread(target=procesar_pendientes, name="sip-sharepoint", daemon=True).start()


_candado = threading.Lock()
_repetir = threading.Event()


def procesar_pendientes(lista_id: int | None = None) -> int:
    """Envía lo que está en cola (y reintenta errores con espera creciente). Devuelve cuántos se enviaron."""
    from .database import SessionLocal
    if not _candado.acquire(blocking=False):
        _repetir.set()  # ya hay un envío en curso: que vuelva a revisar al terminar
        return 0
    enviados = 0
    try:
        while True:
            _repetir.clear()
            with SessionLocal() as db:
                ahora = _ahora()
                q = select(EnvioSharePoint).join(ListaSharePoint).where(ListaSharePoint.activo, (
                    (EnvioSharePoint.estado == "pendiente")
                    | ((EnvioSharePoint.estado == "error") & (EnvioSharePoint.intentos < MAX_INTENTOS))))
                if lista_id:
                    q = q.where(EnvioSharePoint.lista_id == lista_id)
                lote = [e for e in db.scalars(q.order_by(EnvioSharePoint.id).limit(100))
                        if e.estado == "pendiente" or e.actualizado is None
                        or ahora - e.actualizado >= timedelta(minutes=5 * 2 ** min(e.intentos, 6))]
                for env in lote:
                    enviados += _enviar(db, env)
                    db.commit()
            if not _repetir.is_set() and len(lote) < 100:
                break
    finally:
        _candado.release()
    return enviados


def _enviar(db: Session, env: EnvioSharePoint) -> int:
    lista = env.lista
    reg = db.get(_modelo(lista.tipo), env.registro_id)
    base = f"sites/{lista.sitio_id}/lists/{lista.lista_id}/items"
    try:
        if reg is None or env.eliminado:
            if not env.item_id:
                db.delete(env)
                return 0
            campos = campos_lista(lista, None, eliminado=True)
            if campos:
                r = _graph("PATCH", f"{base}/{env.item_id}/fields", campos)
                if r.status_code not in (200, 404):
                    raise ErrorSharePoint(f"HTTP {r.status_code}." + _detalle(r))
        else:
            if reg.estado == BORRADOR and not env.item_id:
                db.delete(env)  # volvió a borrador antes de enviarse
                return 0
            campos = campos_lista(lista, reg)
            r = None
            if env.item_id:
                r = _graph("PATCH", f"{base}/{env.item_id}/fields", campos)
            if r is None or r.status_code == 404:  # nuevo, o lo borraron en SharePoint: se crea de nuevo
                r = _graph("POST", base, {"fields": {k: v for k, v in campos.items() if v is not None}})
                if r.status_code in (200, 201):
                    env.item_id = str(r.json().get("id"))
            if r.status_code not in (200, 201):
                raise ErrorSharePoint(f"HTTP {r.status_code}." + _detalle(r))
        env.estado, env.error, env.intentos = "enviado", None, 0
        env.enviado = env.actualizado = _ahora()
        return 1
    except ErrorSharePoint as e:
        env.estado, env.error = "error", e.mensaje[:1000]
        env.intentos = (env.intentos or 0) + 1
        env.actualizado = _ahora()
        log.warning("SharePoint: no se pudo enviar %s %s: %s", lista.tipo, env.registro_id, e.mensaje[:200])
        return 0


def encolar_existentes(db: Session, lista: ListaSharePoint, desde: date) -> int:
    """Pone en cola las solicitudes (no borrador) de la sede desde una fecha, para enviar el historial."""
    M = _modelo(lista.tipo)
    fecha = M.fecha_inicio if lista.tipo == "vacaciones" else M.fecha
    q = select(M.id).join(Usuario, M.usuario_id == Usuario.id).where(
        Usuario.sede_id == lista.sede_id, M.estado != BORRADOR, fecha >= desde)
    if lista.tipo == "permisos":
        q = q.where(M.tipo != PERMISO_CONSULTA_MEDICA)
    ya = set(db.scalars(select(EnvioSharePoint.registro_id).where(EnvioSharePoint.lista_id == lista.id)))
    n = 0
    for rid in db.scalars(q):
        if rid not in ya:
            db.add(EnvioSharePoint(lista_id=lista.id, registro_id=rid, estado="pendiente", intentos=0, eliminado=False,
                                   actualizado=_ahora()))
            n += 1
    return n


# ---------------- Aprobación en Teams (Power Automate) ----------------
APROBADO_DEF, RECHAZADO_DEF = "Approve", "Reject"


def _valor_campo(v):
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):  # columnas de persona o búsqueda devuelven objetos
        v = v.get("Email") or v.get("LookupValue")
    return str(v).strip() if v not in (None, "") else None


def decision_de(lista: ListaSharePoint, item: dict, reg, db: Session):
    """(estado nuevo, quién resolvió, comentario, nota) a partir del elemento de la lista. Sin decisión: (None, ...)."""
    from .models import RECHAZADO, VALIDADO
    from .services import puede_revisar
    campos = item.get("fields") or {}
    valor = _valor_campo(campos.get(lista.col_decision))
    if not valor:
        return None, None, None, None
    v = normalizar(valor)
    if v in {normalizar(lista.val_aprobado or APROBADO_DEF), "approve", "aprobado", "aprobada", "aprobar"}:
        nuevo = VALIDADO
    elif v in {normalizar(lista.val_rechazado or RECHAZADO_DEF), "reject", "rechazado", "rechazada", "rechazar"}:
        nuevo = RECHAZADO
    else:
        return None, None, None, f"Decisión no reconocida en la columna {lista.col_decision}: «{valor[:60]}»."
    if lista.cuenta_flujo:
        quien = (item.get("lastModifiedBy") or {}).get("user") or {}
        if (quien.get("email") or "").lower() != lista.cuenta_flujo.strip().lower():
            otro = quien.get("displayName") or quien.get("email") or "otra cuenta"
            return None, None, None, f"Decisión ignorada: la escribió {otro} y no la cuenta del flujo ({lista.cuenta_flujo})."
    revisor = reg.aprobador
    correo = _valor_campo(campos.get(lista.col_respondio)) if lista.col_respondio else None
    if correo:
        c = correo.lower()
        revisor = db.scalar(select(Usuario).where((Usuario.email == c) | (Usuario.email_personal == c)))
        if not revisor or not revisor.activo or not puede_revisar(revisor, reg):
            return None, None, None, f"Decisión ignorada: {correo} no puede aprobar esta solicitud en SIP-O."
    if revisor is None:
        return None, None, None, "Decisión ignorada: la solicitud no tiene jefe aprobador y no se indicó quién respondió."
    comentario = _valor_campo(campos.get(lista.col_comentario)) if lista.col_comentario else None
    return nuevo, revisor, comentario, None


def revisar_decisiones() -> int:
    """Lee en las listas con aprobación en Teams la decisión de las solicitudes pendientes y la aplica."""
    from . import correo
    from .bitacora import asignar_actor
    from .database import SessionLocal
    from .models import RECHAZADO, SOLICITADO, VALIDADO
    aplicadas = 0
    with SessionLocal() as db:
        listas = db.scalars(select(ListaSharePoint).where(ListaSharePoint.activo, ListaSharePoint.aprobacion_teams)).all()
        pendientes = []
        for lista in listas:
            M = _modelo(lista.tipo)
            filas = db.execute(select(EnvioSharePoint, M).join(M, M.id == EnvioSharePoint.registro_id).where(
                EnvioSharePoint.lista_id == lista.id, EnvioSharePoint.item_id.is_not(None), M.estado == SOLICITADO)).all()
            pendientes += [(lista, env, reg) for env, reg in filas]
        from .aprobacion_flujo import canal_activo
        pendientes = [p for p in pendientes if not canal_activo(db, p[0].sede_id, p[0].tipo)
                      and p[2].aprobado_jefe_id is None]
        for lista, env, reg in pendientes:
            sel = ",".join(c for c in (lista.col_decision, lista.col_comentario, lista.col_respondio) if c)
            try:
                r = _graph("GET", f"sites/{lista.sitio_id}/lists/{lista.lista_id}/items/{env.item_id}"
                                  f"?$select=id,lastModifiedBy&$expand=fields($select={sel})")
            except ErrorSharePoint as e:
                log.warning("SharePoint: no se pudo leer la decisión de %s: %s", env.item_id, e.mensaje[:200])
                continue
            if r.status_code != 200:
                continue
            nuevo, revisor, comentario, nota = decision_de(lista, r.json(), reg, db)
            if nota:
                if env.decision_nota != nota:
                    env.decision_nota = nota
                    db.commit()
                continue
            if not nuevo:
                continue
            from .services import aprobar
            asignar_actor(db, revisor, "Teams (Power Automate)")
            final = True
            if nuevo == RECHAZADO:
                reg.estado, reg.revisado_por_id, reg.fecha_revision = nuevo, revisor.id, datetime.now()
                reg.motivo_rechazo = comentario or "Rechazado desde Teams"
            else:
                final = aprobar(reg, revisor)
                if comentario and lista.tipo == "permisos":
                    reg.observaciones = comentario
            env.decision_nota = None
            db.commit()
            db.info.pop("bitacora_actor", None)
            aplicadas += 1
            if lista.tipo == "permisos" and nuevo == VALIDADO and final:
                correo.notificar_permiso(reg.id, "permiso_autorizado")
    if aplicadas and not SEGUNDO_PLANO:
        procesar_pendientes()
    return aplicadas


def activar():
    event.listen(Session, "after_flush", _encolar)
    event.listen(Session, "after_commit", _tras_commit)
