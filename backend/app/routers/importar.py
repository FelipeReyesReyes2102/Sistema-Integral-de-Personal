"""Importar empleados desde Excel: vista previa y alta con contraseña inicial y días adeudados por periodo."""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import importacion, reglas
from ..config import settings
from ..database import get_db
from ..models import ROL_OFICINA, ROL_PLANTA, Sede, Usuario
from ..security import auditar, hash_password, puede_usar_password, require_admin
from ..sedes import Alcance, alcance, jornada_por_defecto
from ..services import saldo_periodo, sincronizar_periodos
from .usuarios import _turno_oficina, _validar_sede

router = APIRouter(prefix="/api", tags=["importar empleados"])
MAX_BYTES = 5 * 1024 * 1024


def _texto(dias: float, horas: float) -> str:
    t = f"{dias:g} d" if dias else ""
    if horas:
        t = f"{t} + {horas:g} h" if t else f"{horas:g} h"
    return t or "0"


def _periodos(sede: Sede, ingreso: date, hoy: date):
    """(actual, anterior): los dos últimos periodos ya iniciados según las reglas de la sede (sin tocar la base)."""
    modo = sede.generacion_dias if sede.generacion_dias in reglas.GENERACIONES else "aniversario"
    iniciados = [p for p in reglas.periodos_generados(ingreso, hoy, modo, sede.meses_vigencia or settings.meses_vigencia_periodo,
                                                        settings.vacaciones_al_cumplir_anio) if p.fecha_inicio <= hoy]
    iniciados.sort(key=lambda p: p.fecha_inicio, reverse=True)
    return (iniciados[0] if iniciados else None), (iniciados[1] if len(iniciados) > 1 else None)


def _fijar(db: Session, p, dias: float, horas: float, hoy: date) -> None:
    objetivo = dias * p.horas_por_dia + horas
    actual = saldo_periodo(db, p, hoy=hoy, aplicar_vencimiento=False).horas_disponible
    p.ajuste_horas = round((p.ajuste_horas or 0) + objetivo - actual, 4)
    p.nota_ajuste = "Saldo importado de Excel (vacaciones adeudadas)"


@router.post("/usuarios/importar")
async def importar(request: Request, archivo: UploadFile = File(...), password: str = Form(""), aplicar: bool = Form(False),
                   db: Session = Depends(get_db), admin: Usuario = Depends(require_admin), alc: Alcance = Depends(alcance)):
    """Sin `aplicar` solo devuelve la vista previa; con `aplicar` da de alta a los nuevos (los existentes no se tocan)."""
    contenido = await archivo.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        raise HTTPException(413, "El archivo pesa más de 5 MB.")
    sede_id = alc.defecto
    _validar_sede(db, admin, sede_id)
    sede = db.get(Sede, sede_id)
    try:
        filas, periodos = importacion.interpretar(importacion.leer_xlsx(contenido))
    except (ValueError, KeyError, StopIteration) as e:
        raise HTTPException(422, str(e) if isinstance(e, ValueError) else "No se pudo leer el archivo.")
    if aplicar and len(password) < 8:
        raise HTTPException(422, "La contraseña inicial debe tener al menos 8 caracteres.")

    hoy = date.today()
    existentes = {(n or "").strip().lstrip("0"): (i, nombre) for i, n, nombre in
                  db.execute(select(Usuario.id, Usuario.numero_empleado, Usuario.nombre))}
    vistos: set[str] = set()
    resultado, hash_ = [], hash_password(password) if aplicar else None
    for e in filas:
        clave = e.nomina.lstrip("0")
        rol = ROL_PLANTA if e.planta else ROL_OFICINA
        r = {"fila": e.fila, "nomina": e.nomina, "nombre": e.nombre, "rol": rol, "fecha_ingreso": e.fecha_ingreso,
             "actual": _texto(*e.actual), "anterior": _texto(*e.anterior), "estado": "nuevo", "avisos": list(e.errores)}
        if e.errores:
            r["estado"] = "error"
        elif clave in vistos:
            r["estado"], r["avisos"] = "error", ["Nómina repetida en el archivo"]
        elif clave in existentes:
            r["estado"] = "existe"
            r["avisos"] = [f"Ya registrado como {existentes[clave][1]}: no se modifica"]
        vistos.add(clave)
        resultado.append(r)
        if r["estado"] != "nuevo":
            continue
        if not puede_usar_password(Usuario(rol=rol)):
            r["avisos"].append("Su tipo de usuario no tiene acceso con contraseña (Configuración → Microsoft)")
        actual, anterior = _periodos(sede, e.fecha_ingreso, hoy)
        cargar = []  # (número de periodo, días, horas)
        for (dias, horas), p, titulo in ((e.actual, actual, "periodo actual"), (e.anterior, anterior, "periodo anterior")):
            if not (dias or horas):
                continue
            if p is None:
                r["avisos"].append(f"Trae {_texto(dias, horas)} del {titulo}, pero aún no tiene ese periodo: no se cargan")
            elif p.fecha_vencimiento < hoy:
                r["avisos"].append(f"{_texto(dias, horas)} del Periodo {p.fecha_inicio.year}, que venció el "
                                   f"{p.fecha_vencimiento:%d/%m/%Y}: no se cargan")
            else:
                cargar.append((p.numero, dias, horas))
                r.setdefault("periodos", []).append(f"Periodo {p.fecha_inicio.year}: {_texto(dias, horas)}")
        if rol == ROL_PLANTA:
            r["avisos"].append("Asígnale grupo y turno en Empleados")
        if not aplicar:
            continue
        u = Usuario(sede_id=sede_id, numero_empleado=e.nomina, nombre=e.nombre, rol=rol, fecha_ingreso=e.fecha_ingreso,
                    tipo_jornada_id=jornada_por_defecto(db, sede_id, rol), activo=True,
                    turno_id=_turno_oficina(db, sede_id) if rol == ROL_OFICINA else None,
                    password_hash=hash_, debe_cambiar_password=True)
        db.add(u)
        db.commit()
        por_numero = {p.numero: p for p in sincronizar_periodos(db, u, hoy)}
        for numero, dias, horas in cargar:
            _fijar(db, por_numero[numero], dias, horas, hoy)
        auditar(db, "usuario_creado", usuario_id=u.id, actor_id=admin.id,
                detalle=f"{u.numero_empleado} · {u.rol} · importado de Excel" + (f" · {', '.join(r['periodos'])}" if r.get("periodos") else ""),
                request=request)
        db.commit()
    resumen = {k: sum(1 for r in resultado if r["estado"] == k) for k in ("nuevo", "existe", "error")}
    if aplicar:
        auditar(db, "empleados_importados", actor_id=admin.id,
                detalle=f"{resumen['nuevo']} alta(s) desde «{archivo.filename}» en {sede.nombre}", request=request)
        db.commit()
    return {"sede": sede.nombre, "periodos": periodos, "resumen": resumen, "filas": resultado, "aplicado": aplicar}
