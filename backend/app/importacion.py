"""Importación de empleados desde Excel (catálogo de empleados con vacaciones adeudadas).

Formato esperado (la fila de encabezados puede no ser la primera):
  Código | Empleado | Fecha de ingreso | Periodo 2025-2026 | Periodo 2024-2025 | Comentarios
- Comentario con "12 horas" = personal de planta; si no, oficinas.
- Los saldos son días; "7+8 horas" = 7 días de la jornada más 8 horas.
- El periodo más reciente va al periodo actual del empleado y el anterior al periodo anterior.

El archivo .xlsx se lee con la biblioteca estándar (zip + XML) para no depender de paquetes externos.
"""
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO
from xml.etree import ElementTree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MAX_FILAS = 2000


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def _columna(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def leer_xlsx(contenido: bytes) -> list[list]:
    """Filas de la primera hoja como listas de valores (texto o número)."""
    try:
        z = zipfile.ZipFile(BytesIO(contenido))
    except zipfile.BadZipFile:
        raise ValueError("El archivo no es un Excel .xlsx válido.")
    compartidas = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            compartidas.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    libro = ElementTree.fromstring(z.read("xl/workbook.xml"))
    hoja = libro.find("m:sheets/m:sheet", NS)
    rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    destino = next(r.get("Target") for r in rels if r.get("Id") == hoja.get(REL))
    ruta = destino.lstrip("/") if destino.startswith("/") else f"xl/{destino}"
    filas = []
    for row in ElementTree.fromstring(z.read(ruta)).iter(f"{{{NS['m']}}}row"):
        fila = []
        for c in row.findall("m:c", NS):
            i, tipo = _columna(c.get("r")), c.get("t")
            v = c.find("m:v", NS)
            if tipo == "s" and v is not None:
                valor = compartidas[int(v.text)]
            elif tipo == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
            elif v is None or v.text is None:
                valor = None
            elif tipo in ("str", "b", "e"):
                valor = v.text
            else:
                valor = float(v.text)
            fila.extend([None] * (i + 1 - len(fila)))
            fila[i] = valor
        filas.append(fila)
        if len(filas) > MAX_FILAS:
            raise ValueError(f"El archivo tiene más de {MAX_FILAS} filas.")
    return filas


def _fecha(v) -> date | None:
    if isinstance(v, float):  # número de serie de Excel
        return (datetime(1899, 12, 30) + timedelta(days=v)).date()
    if isinstance(v, str):
        for f in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(v.strip(), f).date()
            except ValueError:
                pass
    return None


def saldo(v) -> tuple[float, float]:
    """(días, horas): 26 → (26, 0); "7+8 horas" → (7, 8); vacío → (0, 0)."""
    if v in (None, ""):
        return 0.0, 0.0
    if isinstance(v, float):
        return v, 0.0
    t = str(v).strip().lower()
    if m := re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*\+\s*(\d+(?:[.,]\d+)?)\s*(h|hr|hrs|hora|horas)", t):
        return float(m[1].replace(",", ".")), float(m[2].replace(",", "."))
    if m := re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(d|dia|dias|días)?", t):
        return float(m[1].replace(",", ".")), 0.0
    if m := re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(h|hr|hrs|hora|horas)", t):
        return 0.0, float(m[1].replace(",", "."))
    raise ValueError(f"saldo no reconocido: «{v}»")


PARTICULAS = {"de", "del", "la", "las", "los", "y", "van", "von", "da", "di"}


def nombre_propio(t: str) -> str:
    """Mayúscula inicial; las partículas (de, del, la…) en minúscula salvo al inicio."""
    palabras = str(t).lower().split()
    return " ".join(p if i and p in PARTICULAS else p.capitalize() for i, p in enumerate(palabras))


def nombre_ordenado(t: str) -> str:
    """«APELLIDO1 APELLIDO2 NOMBRES» → «Nombres Apellido1 Apellido2».

    Los apellidos compuestos con partícula se respetan («SOTO DE ANDA XIMENA» → «Ximena Soto de Anda») y un doble
    espacio indica que falta el segundo apellido («MARTINEZ  LUIS FERNANDO» → «Luis Fernando Martinez»).
    """
    tokens = str(t).strip().split(" ")
    apellidos, i = [], 0
    for _ in range(2):
        partes = []
        while i < len(tokens) and tokens[i].lower() in PARTICULAS:
            partes.append(tokens[i])
            i += 1
        if i < len(tokens):
            partes.append(tokens[i])  # vacío = doble espacio: no hay segundo apellido
            i += 1
        apellidos.append(" ".join(x for x in partes if x))
    nombres = " ".join(x for x in tokens[i:] if x)
    if not nombres:  # menos de tres palabras: no se puede separar con seguridad
        return nombre_propio(t)
    return nombre_propio(f"{nombres} {' '.join(a for a in apellidos if a)}")


@dataclass
class Fila:
    fila: int
    nomina: str
    nombre: str
    fecha_ingreso: date | None
    planta: bool
    actual: tuple[float, float] = (0.0, 0.0)
    anterior: tuple[float, float] = (0.0, 0.0)
    errores: list[str] = field(default_factory=list)


def interpretar(filas: list[list]) -> tuple[list[Fila], list[str]]:
    """Encuentra los encabezados y convierte cada empleado. Devuelve (empleados, nombres de los periodos)."""
    for n, f in enumerate(filas):
        cab = [_norm(x) for x in f]
        if "empleado" in cab and any(c.startswith("fechadeingreso") or c == "ingreso" for c in cab):
            break
    else:
        raise ValueError("No encontré los encabezados (Código, Empleado, Fecha de ingreso…).")
    col = {}
    periodos = []
    for i, c in enumerate(cab):
        if c in ("codigo", "nomina", "numerodeempleado", "numerodenomina", "noempleado") and "nomina" not in col:
            col["nomina"] = i
        elif c in ("empleado", "nombre") and "nombre" not in col:
            col["nombre"] = i
        elif (c.startswith("fechadeingreso") or c == "ingreso") and "ingreso" not in col:
            col["ingreso"] = i
        elif c.startswith("comentario"):
            col["comentario"] = i
        elif c.startswith("periodo"):
            anios = [int(a) for a in re.findall(r"\d{4}", str(f[i]))]
            periodos.append((max(anios) if anios else 0, i, str(f[i]).strip()))
    if "nomina" not in col or "nombre" not in col:
        raise ValueError("Faltan las columnas Código (nómina) y Empleado.")
    periodos.sort(reverse=True)  # el más reciente primero
    g = lambda r, k: r[col[k]] if k in col and col[k] < len(r) else None  # noqa: E731
    out = []
    for k, r in enumerate(filas[n + 1:], start=n + 2):
        nombre, nomina = g(r, "nombre"), g(r, "nomina")
        if not nombre or not str(nombre).strip() or _norm(nombre) in ("empresa", "total", "totales"):
            continue  # vacías o fila de totales al final del reporte
        if isinstance(nomina, float):
            nomina = str(int(nomina)) if nomina.is_integer() else str(nomina)
        e = Fila(fila=k, nomina=str(nomina or "").strip(), nombre=nombre_ordenado(nombre), fecha_ingreso=_fecha(g(r, "ingreso")),
                 planta="12horas" in _norm(g(r, "comentario")))
        if not e.nomina:
            e.errores.append("Sin número de nómina")
        if not e.fecha_ingreso:
            e.errores.append("Sin fecha de ingreso")
        for destino, (_, i, titulo) in zip(("actual", "anterior"), periodos):
            try:
                setattr(e, destino, saldo(r[i] if i < len(r) else None))
            except ValueError as ex:
                e.errores.append(f"{titulo}: {ex}")
        out.append(e)
    return out, [t for _, _, t in periodos[:2]]
