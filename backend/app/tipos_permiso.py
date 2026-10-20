"""Tipos de permiso configurables por sede.

Cada sede tiene los 4 tipos base (llegada tarde, salida temprana, salida durante la jornada y home office), que no se
pueden borrar, y los que agregue GH. Un tipo es por horas (un día, con horario) o por días (un rango, como el home
office), puede pedir el tipo de nómina y puede tener un límite de días u horas por mes, por año o sin límite.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import reglas
from .models import ESTADOS_ACTIVOS, Permiso, Sede, TipoPermisoSede, Usuario

# clave, nombre, modalidad, pide_nomina, color
BASE = [
    ("llegada_tarde", "Llegada tarde", "horas", True, "#f57c00"),
    ("salida_temprana", "Salida temprana", "horas", True, "#7b1fa2"),
    ("salida_intermedia", "Salida durante la jornada", "horas", True, "#c2185b"),
    ("home_office", "Home office", "dias", False, "#2f6db5"),
]
NOMBRES_BASE = {c: n for c, n, *_ in BASE} | {"consulta_medica": "Consulta médica"}
OTRO = "otro_permiso"  # categoría del calendario para los tipos agregados por la sede


def categoria(clave: str) -> str:
    return clave if clave in NOMBRES_BASE else OTRO


def de_sede(db: Session, sede_id: int | None, solo_activos: bool = False) -> list[TipoPermisoSede]:
    """Tipos de la sede; crea los tipos base si aún no existen (según lo que la sede tenía habilitado)."""
    if not sede_id:
        return []
    filas = list(db.scalars(select(TipoPermisoSede).where(TipoPermisoSede.sede_id == sede_id)
                            .order_by(TipoPermisoSede.orden, TipoPermisoSede.id)))
    claves = {t.clave for t in filas}
    faltan = [b for b in BASE if b[0] not in claves]
    if faltan:
        sede = db.get(Sede, sede_id)
        habilitados = set((sede.tipos_permiso or "").split(",")) if sede else set()
        for i, (clave, nombre, modalidad, nomina, color) in enumerate(BASE):
            if clave in claves:
                continue
            t = TipoPermisoSede(sede_id=sede_id, clave=clave, nombre=nombre, modalidad=modalidad, pide_nomina=nomina,
                                color=color, base=True, activo=clave in habilitados, orden=i,
                                max_dias_solicitud=(sede.home_office_max_dias if sede and modalidad == "dias" else None))
            db.add(t)
            filas.append(t)
        db.flush()
        filas.sort(key=lambda t: (t.orden, t.id or 0))
    return [t for t in filas if t.activo] if solo_activos else filas


def obtener(db: Session, sede_id: int | None, clave: str) -> TipoPermisoSede | None:
    return next((t for t in de_sede(db, sede_id) if t.clave == clave), None)


def nombre(db: Session | None, sede_id: int | None, clave: str) -> str:
    if clave in NOMBRES_BASE or db is None:
        return NOMBRES_BASE.get(clave, clave)
    t = obtener(db, sede_id, clave)
    return t.nombre if t else clave


def por_dias(db: Session | None, sede_id: int | None, clave: str) -> bool:
    if clave == "home_office" or db is None:
        return clave == "home_office"
    t = obtener(db, sede_id, clave)
    return bool(t and t.modalidad == "dias")


def sincronizar_sede(db: Session, sede: Sede):
    """Mantiene los campos anteriores de la sede (tipos habilitados y máximo de home office) al día."""
    tipos = de_sede(db, sede.id)
    sede.tipos_permiso = ",".join(t.clave for t in tipos if t.activo)
    ho = next((t for t in tipos if t.clave == "home_office"), None)
    if ho and ho.max_dias_solicitud:
        sede.home_office_max_dias = ho.max_dias_solicitud


def nueva_clave(db: Session, sede_id: int, nombre_tipo: str) -> str:
    base = unicodedata.normalize("NFKD", nombre_tipo).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:24] or "permiso"
    existentes = {t.clave for t in de_sede(db, sede_id)} | set(NOMBRES_BASE) | {OTRO}
    clave, n = base, 2
    while clave in existentes:
        clave, n = f"{base[:21]}_{n}", n + 1
    return clave


# ---------------- Límites ----------------
def ventana(t: TipoPermisoSede, fecha: date) -> tuple[date, date] | None:
    if t.limite_periodo == "mes":
        inicio = fecha.replace(day=1)
        fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return inicio, fin
    if t.limite_periodo == "anio":
        return date(fecha.year, 1, 1), date(fecha.year, 12, 31)
    return None


def _uso_de(db: Session, u: Usuario, t: TipoPermisoSede, desde: date, hasta: date, excluir_id: int | None) -> float:
    """Días (o horas) usados del tipo dentro de la ventana, contando borradores, solicitados y validados."""
    from .services import ciclo_de, festivos_de
    q = select(Permiso).where(Permiso.usuario_id == u.id, Permiso.tipo == t.clave, Permiso.estado.in_(ESTADOS_ACTIVOS),
                              Permiso.fecha <= hasta, func.coalesce(Permiso.fecha_fin, Permiso.fecha) >= desde)
    if excluir_id:
        q = q.where(Permiso.id != excluir_id)
    total = 0.0
    for p in db.scalars(q):
        if t.limite_unidad == "horas":
            total += p.horas if desde <= p.fecha <= hasta else 0
        elif t.modalidad == "dias":
            a, b = max(p.fecha, desde), min(p.fecha_fin or p.fecha, hasta)
            total += len(reglas.dias_laborales(a, b, ciclo_de(u), festivos_de(db, u, a, b)))
        else:
            total += 1 if desde <= p.fecha <= hasta else 0
    return total


def uso(db: Session, u: Usuario, t: TipoPermisoSede, fecha: date, excluir_id: int | None = None) -> dict:
    if not t.limite_cantidad:
        return {"limite": None, "usado": 0, "unidad": t.limite_unidad, "periodo": t.limite_periodo}
    v = ventana(t, fecha)
    desde, hasta = v if v else (date(1900, 1, 1), date(2999, 12, 31))
    return {"limite": t.limite_cantidad, "usado": _uso_de(db, u, t, desde, hasta, excluir_id), "unidad": t.limite_unidad,
            "periodo": t.limite_periodo, "desde": desde if v else None, "hasta": hasta if v else None}


def texto_periodo(periodo: str | None) -> str:
    return {"mes": "por mes", "anio": "por año"}.get(periodo or "", "en total")


def validar_limite(db: Session, u: Usuario, t: TipoPermisoSede, fecha: date, fecha_fin: date | None, horas: float,
                   dias: int, excluir_id: int | None):
    """El permiso no puede pasar el límite del tipo en ninguna de las ventanas (mes o año) que toca."""
    if not t.limite_cantidad:
        return
    fin = fecha_fin or fecha
    revisadas, d = set(), fecha
    from .services import ciclo_de, festivos_de
    while d <= fin:
        v = ventana(t, d) or (date(1900, 1, 1), date(2999, 12, 31))
        if v not in revisadas:
            revisadas.add(v)
            usado = _uso_de(db, u, t, v[0], v[1], excluir_id)
            if t.limite_unidad == "horas":
                nuevo = horas
            elif t.modalidad == "dias":
                a, b = max(fecha, v[0]), min(fin, v[1])
                nuevo = len(reglas.dias_laborales(a, b, ciclo_de(u), festivos_de(db, u, a, b)))
            else:
                nuevo = 1
            if usado + nuevo > t.limite_cantidad + 1e-9:
                unidad = "h" if t.limite_unidad == "horas" else "permiso(s)" if t.modalidad == "horas" else "día(s)"
                quedan = max(t.limite_cantidad - usado, 0)
                raise HTTPException(422, f"{t.nombre}: el límite es {t.limite_cantidad:g} {unidad} {texto_periodo(t.limite_periodo)}"
                                         f" y ya llevas {usado:g}; te quedan {quedan:g}.")
        d = v[1] + timedelta(days=1)
