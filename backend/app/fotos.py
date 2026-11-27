"""Fotos de los empleados guardadas en una biblioteca de documentos de SharePoint (Microsoft Graph).

- El super administrador pega la URL de una biblioteca (o de una carpeta dentro de ella) en Super administración →
  Fotos en SharePoint. Si no hay biblioteca conectada, las fotos se guardan en la base de datos como antes.
- Con la biblioteca activa, cada foto nueva (de Microsoft al dar de alta o al iniciar sesión) se sube como
  "<nómina> - <nombre>.jpg" y en la base solo queda el id del archivo; los bytes se borran de la base cuando
  SharePoint confirma el archivo con el mismo tamaño. Si Microsoft no responde, la foto se queda en la base y se
  mueve después con el botón «Mover a SharePoint».
- Para mostrarla, el servidor la descarga de SharePoint (los navegadores de caseta no tienen sesión de Microsoft)
  y guarda en memoria las más recientes; el navegador la guarda en su caché un día.
- Quitar la foto envía el archivo a la papelera de reciclaje del sitio (recuperable desde SharePoint).
- Requiere el permiso de aplicación Sites.ReadWrite.All (o Sites.Selected con escritura en el sitio).
"""
import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import microsoft
from .config import settings
from .models import ConfiguracionApp, Usuario
from .security import ahora

log = logging.getLogger("sip.fotos")
CLAVE = "FOTOS_SHAREPOINT"
CARPETA_DEFECTO = "Fotos SIP-O"
SEGUNDO_PLANO = True  # las pruebas lo apagan para subir en el mismo hilo


class ErrorFotos(Exception):
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


# ---------------- Configuración ----------------
def config(db: Session) -> dict | None:
    fila = db.get(ConfiguracionApp, CLAVE)
    if not fila or not fila.valor:
        return None
    try:
        return json.loads(fila.valor)
    except ValueError:
        return None


def activa(db: Session) -> dict | None:
    c = config(db)
    return c if c and c.get("activo") and c.get("drive_id") else None


def guardar_config(db: Session, datos: dict | None, actor_id: int | None):
    fila = db.get(ConfiguracionApp, CLAVE)
    if datos is None:
        if fila:
            db.delete(fila)
        db.commit()
        return
    if fila is None:
        fila = ConfiguracionApp(clave=CLAVE, cifrado=False)
        db.add(fila)
    fila.valor = json.dumps(datos, ensure_ascii=False)
    fila.actualizado, fila.actualizado_por_id = ahora(), actor_id
    db.commit()


# ---------------- Graph ----------------
def _graph(metodo: str, ruta: str, *, json_=None, contenido: bytes | None = None, tipo: str | None = None,
           seguir: bool = False) -> httpx.Response:
    if not settings.microsoft_configurado and not settings.graph_configurado:
        raise ErrorFotos("Configura primero la conexión con Microsoft (Super administración → Conexión con Microsoft).")
    for intento in range(2):
        try:
            token = microsoft.token_aplicacion()
            cab = {"Authorization": f"Bearer {token}"}
            if tipo:
                cab["Content-Type"] = tipo
            with microsoft._cliente() as c:
                r = c.request(metodo, f"{settings.microsoft_graph_url}/{ruta}", json=json_, content=contenido,
                              headers=cab, follow_redirects=seguir)
        except microsoft.ErrorMicrosoft as e:
            raise ErrorFotos(e.mensaje)
        except httpx.HTTPError as e:
            raise ErrorFotos(f"No se pudo contactar a Microsoft ({type(e).__name__}).")
        if r.status_code not in (401, 403) or intento:
            break
        microsoft._token_app.update(valor=None, expira=0)  # el token en caché pudo ser anterior al permiso
    if r.status_code in (401, 403):
        raise ErrorFotos("Microsoft negó el acceso a la biblioteca. La aplicación necesita el permiso de aplicación "
                         "Sites.ReadWrite.All (o Sites.Selected con escritura en este sitio) con consentimiento de "
                         "administrador." + _detalle(r))
    return r


def _detalle(r: httpx.Response) -> str:
    try:
        texto = str(r.json().get("error", {}).get("message", ""))[:250]
    except ValueError:
        return ""
    return f" Detalle de Microsoft: {texto}" if texto else ""


def _ruta_url(url: str) -> tuple[str, str]:
    """(host, ruta) de la biblioteca o carpeta, también desde «AllItems.aspx?id=/sites/…/Carpeta»."""
    u = urlparse((url or "").strip())
    if u.scheme != "https" or not u.netloc.lower().endswith(".sharepoint.com"):
        raise ErrorFotos("Pega la URL completa de la biblioteca de SharePoint (https://<empresa>.sharepoint.com/...).")
    ruta = unquote(u.path)
    carpeta_id = parse_qs(u.query).get("id")
    if carpeta_id:  # vista de una carpeta: la ruta real viene en ?id=
        ruta = unquote(carpeta_id[0])
    ruta = re.sub(r"/Forms/[^/]+\.aspx$", "", ruta, flags=re.IGNORECASE)
    ruta = re.sub(r"/[^/]+\.aspx$", "", ruta, flags=re.IGNORECASE)
    return u.netloc.lower(), ruta.rstrip("/")


CORREO = re.compile(r"^[^@\s/]+@[^@\s/]+\.[a-z]{2,}$", re.IGNORECASE)


def conectar(url: str, carpeta: str | None = None) -> dict:
    """Busca el sitio, la biblioteca y la carpeta, y comprueba que se pueda escribir creando la carpeta.

    En lugar de la URL se puede indicar una cuenta de Microsoft 365 (p. ej. ti.mexico@o-tek.com): las fotos se
    guardan en el OneDrive de esa cuenta."""
    url = (url or "").strip()
    if CORREO.match(url):
        return _conectar_onedrive(url.lower(), carpeta)
    host, ruta = _ruta_url(url)
    partes = [p for p in ruta.split("/") if p]
    ruta_sitio = "/" + "/".join(partes[:2]) if len(partes) >= 2 and partes[0].lower() in ("sites", "teams", "personal") else ""
    r = _graph("GET", f"sites/{host}:{quote(ruta_sitio)}" if ruta_sitio else f"sites/{host}")
    if r.status_code == 404:
        raise ErrorFotos(f"No se encontró el sitio {host}{ruta_sitio}.")
    if r.status_code != 200:
        raise ErrorFotos(f"Microsoft respondió HTTP {r.status_code} al buscar el sitio." + _detalle(r))
    sitio = r.json()
    r = _graph("GET", f"sites/{sitio['id']}/drives?$select=id,name,webUrl")
    if r.status_code != 200:
        raise ErrorFotos(f"Microsoft respondió HTTP {r.status_code} al leer las bibliotecas del sitio." + _detalle(r))
    buscada = ruta.lower()
    drive, resto = None, ""
    for d in r.json().get("value", []):  # la biblioteca cuya dirección es el inicio más largo de la URL
        base = unquote(urlparse(d.get("webUrl", "")).path).rstrip("/")
        if base and (buscada == base.lower() or buscada.startswith(base.lower() + "/")):
            if not drive or len(base) > len(drive[1]):
                drive, resto = (d, base), ruta[len(base):].strip("/")
    if not drive:
        raise ErrorFotos("La URL no corresponde a una biblioteca de documentos del sitio. Abre la biblioteca (por "
                         "ejemplo «Documentos») en SharePoint y copia la dirección.")
    d = drive[0]
    carpeta = _validar_carpeta(carpeta, resto)
    _crear_carpeta(d["id"], carpeta)
    return {"url": url.strip(), "sitio_id": sitio["id"], "sitio_nombre": sitio.get("displayName"), "drive_id": d["id"],
            "drive_nombre": d.get("name"), "carpeta": carpeta,
            "web_url": f"{d.get('webUrl', '').rstrip('/')}/{quote(carpeta)}"}


def _validar_carpeta(carpeta: str | None, resto: str = "") -> str:
    carpeta = (carpeta or "").strip().strip("/") or resto or CARPETA_DEFECTO
    if re.search(r'[~"#%&*:<>?\\{|}]', carpeta):
        raise ErrorFotos('El nombre de la carpeta no puede llevar los caracteres ~ " # % & * : < > ? \\ { | }.')
    return carpeta


def _conectar_onedrive(cuenta: str, carpeta: str | None) -> dict:
    r = _graph("GET", f"users/{quote(cuenta)}/drive?$select=id,name,webUrl,owner")
    if r.status_code == 404:
        raise ErrorFotos(f"No se encontró el OneDrive de {cuenta}. Verifica que la cuenta exista, tenga licencia con "
                         "OneDrive y que haya entrado a OneDrive al menos una vez." + _detalle(r))
    if r.status_code != 200:
        raise ErrorFotos(f"Microsoft respondió HTTP {r.status_code} al buscar el OneDrive de {cuenta}." + _detalle(r))
    d = r.json()
    carpeta = _validar_carpeta(carpeta)
    _crear_carpeta(d["id"], carpeta)
    return {"url": cuenta, "sitio_id": None, "sitio_nombre": f"OneDrive de {cuenta}", "drive_id": d["id"],
            "drive_nombre": d.get("name") or "OneDrive", "carpeta": carpeta,
            "web_url": f"{d.get('webUrl', '').rstrip('/')}/{quote(carpeta)}"}


def _crear_carpeta(drive_id: str, carpeta: str):
    padre = "root"
    for parte in carpeta.split("/"):
        r = _graph("POST", f"drives/{drive_id}/{'root' if padre == 'root' else 'items/' + padre}/children",
                   json_={"name": parte, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
        if r.status_code == 409:  # ya existe
            ruta = carpeta[:carpeta.index(parte) + len(parte)]
            r = _graph("GET", f"drives/{drive_id}/root:/{quote(ruta)}")
        if r.status_code not in (200, 201):
            raise ErrorFotos(f"No se pudo crear la carpeta «{carpeta}» (HTTP {r.status_code})." + _detalle(r))
        padre = r.json()["id"]


# ---------------- Fotos ----------------
def _ref(u: Usuario) -> tuple[str, str] | None:
    """(biblioteca, archivo) de la foto; cada foto recuerda su biblioteca por si después se conecta otra."""
    if not u.foto_ref or "|" not in u.foto_ref:
        return None
    drive, item = u.foto_ref.split("|", 1)
    return drive, item


def _nombre_archivo(u: Usuario, tipo: str) -> str:
    ext = {"image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(tipo, "jpg")
    nombre = re.sub(r'[~"#%&*:<>?/\\{|}]+', " ", f"{u.numero_empleado or u.id} - {u.nombre}").strip()
    return f"{re.sub(r' +', ' ', nombre)[:120]}.{ext}"


def subir(db: Session, u: Usuario, cfg: dict | None = None) -> bool:
    """Sube a SharePoint la foto que está en la base y la borra de la base si SharePoint la confirmó."""
    cfg = cfg or activa(db)
    if not cfg or not u.foto or not u.foto_tipo:
        return False
    contenido, tipo = u.foto, u.foto_tipo
    r = None
    ref = _ref(u)
    if ref and ref[0] == cfg["drive_id"]:  # mismo archivo: SharePoint guarda la versión anterior
        r = _graph("PUT", f"drives/{ref[0]}/items/{ref[1]}/content", contenido=contenido, tipo=tipo)
        if r.status_code == 404:
            r = None
    if r is None:
        ruta = quote(f"{cfg['carpeta']}/{_nombre_archivo(u, tipo)}")
        r = _graph("PUT", f"drives/{cfg['drive_id']}/root:/{ruta}:/content?@microsoft.graph.conflictBehavior=replace",
                   contenido=contenido, tipo=tipo)
    if r.status_code not in (200, 201):
        raise ErrorFotos(f"SharePoint respondió HTTP {r.status_code} al subir la foto." + _detalle(r))
    item = r.json()
    if int(item.get("size") or -1) != len(contenido):
        raise ErrorFotos("SharePoint no confirmó la foto completa; se conserva en el servidor.")
    nuevo = f"{cfg['drive_id']}|{item['id']}"
    _cache_poner(nuevo, contenido)
    u.foto_ref, u.foto_huella, u.foto = nuevo, _huella(contenido), None
    db.commit()
    return True


def tras_cambio(u: Usuario, quitada: tuple[str, str] | None = None):
    """Después de guardar al empleado: subir su foto nueva a SharePoint (o mandar a la papelera la que se quitó)
    sin hacer esperar a quien guardó."""
    if not u.foto and not quitada:
        return
    args = (u.id if u.foto else None, quitada)
    if SEGUNDO_PLANO:
        threading.Thread(target=_tras_cambio, args=args, daemon=True, name=f"foto-{u.id}").start()
    else:
        _tras_cambio(*args)


def _tras_cambio(uid: int | None, quitada: tuple[str, str] | None):
    from .database import SessionLocal
    borrar_archivo(quitada)
    if uid is None:
        return
    db = SessionLocal()
    try:
        u = db.get(Usuario, uid)
        if u and activa(db):
            subir(db, u)
    except ErrorFotos as e:
        log.warning("Foto de %s no subida a SharePoint (queda en el servidor): %s", uid, e.mensaje)
    except Exception:  # noqa: BLE001 - nunca debe afectar al guardado del empleado
        log.exception("Error al subir la foto de %s", uid)
    finally:
        db.close()


def quitar(u: Usuario) -> tuple[str, str] | None:
    """Quita la foto del empleado; devuelve el archivo de SharePoint para enviarlo a la papelera tras guardar."""
    ref = _ref(u)
    if u.foto_ref:
        with _candado:
            if u.foto_ref in _cache:
                _cache_bytes[0] -= len(_cache.pop(u.foto_ref))
    u.foto = u.foto_tipo = u.foto_ref = u.foto_huella = None
    return ref


def borrar_archivo(ref: tuple[str, str] | None):
    """Envía el archivo a la papelera de reciclaje del sitio (recuperable desde SharePoint)."""
    if not ref:
        return
    try:
        r = _graph("DELETE", f"drives/{ref[0]}/items/{ref[1]}")
        if r.status_code not in (204, 404):
            log.warning("SharePoint respondió HTTP %s al quitar una foto", r.status_code)
    except ErrorFotos as e:
        log.warning("No se pudo enviar a la papelera una foto: %s", e.mensaje)


def mover_pendientes(db: Session, limite: int = 500) -> dict:
    """Sube a SharePoint las fotos que siguen en la base de datos."""
    cfg = activa(db)
    if not cfg:
        raise ErrorFotos("Conecta y activa primero la biblioteca de SharePoint.")
    movidas, errores = 0, []
    ids = db.scalars(select(Usuario.id).where(Usuario.foto.is_not(None)).order_by(Usuario.id).limit(limite)).all()
    for uid in ids:
        u = db.get(Usuario, uid)
        try:
            movidas += subir(db, u, cfg)
        except ErrorFotos as e:
            db.rollback()
            errores.append(f"{u.nombre}: {e.mensaje}")
            if len(errores) >= 5 and not movidas:  # Microsoft no responde: no insistir con todas
                break
    return {"movidas": movidas, "errores": errores[:10], "pendientes": pendientes(db)}


def _huella(contenido: bytes) -> str:
    return hashlib.sha1(contenido).hexdigest()[:16]


def actualizar_desde_microsoft(db: Session, desde: int = 0, lote: int = 25) -> dict:
    """Vuelve a traer de Microsoft la foto de los empleados activos con cuenta de Microsoft, en la mayor resolución
    disponible (432x432). Va por lotes para no exceder el tiempo de la petición: `desde` es el último id procesado.

    Si la foto no cambió no se toca; si Microsoft no tiene foto de la persona, se conserva la que hay."""
    if not settings.graph_configurado:
        raise ErrorFotos("La consulta de empleados en Microsoft (Graph) no está habilitada.")
    try:
        token = microsoft.token_aplicacion()
    except microsoft.ErrorMicrosoft as e:
        raise ErrorFotos(e.mensaje)
    cuenta = (Usuario.microsoft_oid.is_not(None)) | (Usuario.email.is_not(None))
    base = select(Usuario.id).where(Usuario.activo.is_(True), cuenta)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    ids = db.scalars(base.where(Usuario.id > desde).order_by(Usuario.id).limit(lote)).all()
    cfg = activa(db)
    res = {"revisadas": 0, "actualizadas": 0, "sin_foto": 0, "iguales": 0, "errores": [], "total": total,
           "siguiente": ids[-1] if ids else None}
    for uid in ids:
        u = db.get(Usuario, uid)
        res["revisadas"] += 1
        imagen = microsoft.foto(token, f"users/{u.microsoft_oid or u.email}")
        if not imagen:
            res["sin_foto"] += 1
            continue
        contenido, tipo = imagen
        actual = u.foto or None
        if (actual and actual == contenido) or (not actual and u.foto_huella == _huella(contenido)):
            res["iguales"] += 1
            continue
        u.foto, u.foto_tipo = contenido, tipo
        db.commit()
        res["actualizadas"] += 1
        if cfg:
            try:
                subir(db, u, cfg)
            except ErrorFotos as e:
                db.rollback()
                res["errores"].append(f"{u.nombre}: {e.mensaje} (la foto quedó en el servidor)")
    if len(ids) < lote:
        res["siguiente"] = None
    return res


def pendientes(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Usuario).where(Usuario.foto.is_not(None))) or 0


def en_sharepoint(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Usuario).where(Usuario.foto_ref.is_not(None))) or 0


# ---------------- Lectura con caché en memoria ----------------
CACHE_MAX = 40 * 1024 * 1024  # 40 MB por proceso
_cache: OrderedDict[str, bytes] = OrderedDict()
_cache_bytes = [0]
_candado = threading.Lock()


def _cache_poner(ref: str, contenido: bytes):
    with _candado:
        if ref in _cache:
            _cache_bytes[0] -= len(_cache.pop(ref))
        _cache[ref] = contenido
        _cache_bytes[0] += len(contenido)
        while _cache_bytes[0] > CACHE_MAX and _cache:
            _, viejo = _cache.popitem(last=False)
            _cache_bytes[0] -= len(viejo)


def leer(db: Session, u: Usuario) -> bytes | None:
    """Bytes de la foto: de la base, de la memoria o descargada de SharePoint."""
    if u.foto:
        return u.foto
    if not u.foto_ref:
        return None
    with _candado:
        if u.foto_ref in _cache:
            _cache.move_to_end(u.foto_ref)
            return _cache[u.foto_ref]
    ref = _ref(u)
    if not ref:
        return None
    try:
        r = _graph("GET", f"drives/{ref[0]}/items/{ref[1]}/content", seguir=True)
    except ErrorFotos as e:
        log.warning("No se pudo descargar la foto de %s: %s", u.id, e.mensaje)
        return None
    if r.status_code != 200 or not r.content:
        log.warning("SharePoint respondió HTTP %s al descargar la foto de %s", r.status_code, u.id)
        return None
    _cache_poner(u.foto_ref, r.content)
    return r.content
