"""Reglas de negocio puras (sin base de datos) para vacaciones y permisos.

Oficinas: el día equivale a 8 h. Año 1 = 12 días y aumenta según la tabla de antigüedad.
Planta:    se otorgan las mismas horas que a oficinas (días de ley x 8 h) pero cada día
           de planta consume 12 h. Año 1 = 12 x 8 = 96 h / 12 = 8 días.
Bloque:    en cada periodo se debe tomar AL MENOS UNA VEZ un bloque de días laborales seguidos
           (6 oficinas / 4 planta). Se permiten solicitudes más cortas siempre que, mientras no se
           haya tomado ese bloque, el saldo restante siga alcanzando para tomarlo.
Vigencia:  los días de cada periodo se pueden disfrutar durante 18 meses desde que se otorgan;
           después, el saldo no usado del periodo se pierde.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

from dateutil.relativedelta import relativedelta

HORAS_DIA_LEY = 8
HORAS_DIA = {"oficina": 8, "planta": 12}
MIN_DIAS_SEGUIDOS = {"oficina": 6, "planta": 4}

# Tabla por defecto (LFT México, reforma 2023)
TABLA_ANTIGUEDAD_DEFAULT: list[tuple[int, int, int]] = [
    (1, 1, 12), (2, 2, 14), (3, 3, 16), (4, 4, 18), (5, 5, 20),
    (6, 10, 22), (11, 15, 24), (16, 20, 26), (21, 25, 28), (26, 30, 30), (31, 36, 32),
]


def categoria(rol: str) -> str:
    """Los administradores se rigen por las reglas de oficinas."""
    return "planta" if rol == "planta" else "oficina"


def dias_por_antiguedad(anios: int, tabla: Iterable[tuple[int, int, int]]) -> int:
    tabla = sorted(tabla)
    if not tabla:
        return 0
    for desde, hasta, dias in tabla:
        if desde <= anios <= hasta:
            return dias
    if anios > tabla[-1][1]:
        # Más allá de la tabla: +2 días por cada bloque de 5 años adicional
        extra = math.ceil((anios - tabla[-1][1]) / 5)
        return tabla[-1][2] + 2 * extra
    return tabla[0][2]


def horas_otorgadas(dias_ley: int) -> float:
    return float(dias_ley * HORAS_DIA_LEY)


def horas_a_dias(horas: float, cat: str | int) -> float:
    """Horas a días de la jornada (`cat` puede ser la categoría o directamente las horas por día)."""
    hd = cat if isinstance(cat, int) else HORAS_DIA[cat]
    return round(horas / hd, 2)


def horas_perdidas(horas_disponibles: float, vencimiento: date, hoy: date) -> float:
    """Horas que se pierden por vencimiento: todo el saldo no usado de un periodo vencido."""
    return max(horas_disponibles, 0.0) if vencimiento < hoy else 0.0


@dataclass
class Ciclo:
    """Describe qué días trabaja un empleado."""
    tipo: str = "semanal"                 # semanal | rotativo
    dias_semana: tuple[int, ...] = (0, 1, 2, 3, 4)
    dias_trabajo: int = 4
    dias_descanso: int = 4
    fecha_inicio: date | None = None

    def es_laboral(self, d: date) -> bool:
        if self.tipo == "rotativo" and self.fecha_inicio and (self.dias_trabajo + self.dias_descanso) > 0:
            pos = (d - self.fecha_inicio).days % (self.dias_trabajo + self.dias_descanso)
            return pos < self.dias_trabajo
        return d.weekday() in self.dias_semana


def parse_dias_semana(texto: str | None) -> tuple[int, ...]:
    if not texto:
        return (0, 1, 2, 3, 4)
    return tuple(sorted({int(x) for x in texto.split(",") if x.strip().isdigit() and 0 <= int(x) <= 6}))


def dias_laborales(inicio: date, fin: date, ciclo: Ciclo, festivos: set[date]) -> list[date]:
    dias, d = [], inicio
    while d <= fin:
        if ciclo.es_laboral(d) and d not in festivos:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def sumar_anios(d: date, anios: int) -> date:
    return d + relativedelta(years=anios)  # maneja 29 de febrero


def anios_cumplidos(ingreso: date, hoy: date) -> int:
    return relativedelta(hoy, ingreso).years


@dataclass
class PeriodoCalc:
    numero: int
    fecha_inicio: date
    fecha_vencimiento: date
    fraccion: float = 1.0  # parte de los días del periodo que ya se generó (mensual / primer año calendario)


def periodos_hasta(ingreso: date, hoy: date, al_cumplir_anio: bool, meses_vigencia: int) -> list[PeriodoCalc]:
    """Periodos (años de servicio) que ya están disponibles a la fecha `hoy`."""
    res, n = [], 1
    while True:
        inicio = sumar_anios(ingreso, n if al_cumplir_anio else n - 1)
        if inicio > hoy:
            break
        venc = inicio + relativedelta(months=meses_vigencia) - timedelta(days=1)
        res.append(PeriodoCalc(n, inicio, venc))
        n += 1
    return res


GENERACIONES = ("aniversario", "calendario", "mensual")


def meses_completos(desde: date, hasta: date) -> int:
    r = relativedelta(hasta, desde)
    return r.years * 12 + r.months


def periodos_generados(ingreso: date, hoy: date, modo: str, meses_vigencia: int,
                       al_cumplir_anio: bool = True) -> list[PeriodoCalc]:
    """Periodos disponibles a la fecha `hoy` según cómo genera la sede los días.

    - aniversario: el periodo n (año de servicio n) se otorga completo al cumplirlo.
    - calendario: el periodo n se otorga el 1 de enero del año (ingreso + n); el primero es proporcional a los meses
      que se trabajaron en el año de ingreso. Los días son los de los años de servicio que se cumplen en ese año.
    - mensual: el periodo n empieza al iniciar el año de servicio n y sus días se acumulan cada mes cumplido; vence
      `meses_vigencia` después de completarse.
    """
    if modo == "calendario":
        res, n = [], 1
        while True:
            inicio = date(ingreso.year + n, 1, 1)
            if inicio > hoy:
                break
            fraccion = 1.0
            if n == 1:  # meses trabajados en el año de ingreso (el mes de ingreso cuenta si entró antes del día 16)
                meses = 12 - ingreso.month + (1 if ingreso.day <= 15 else 0)
                fraccion = round(max(0, min(12, meses)) / 12, 4)
            venc = inicio + relativedelta(months=meses_vigencia) - timedelta(days=1)
            res.append(PeriodoCalc(n, inicio, venc, fraccion))
            n += 1
        return res
    if modo == "mensual":
        res, n = [], 1
        while True:
            inicio = sumar_anios(ingreso, n - 1)
            if inicio > hoy:
                break
            completo = sumar_anios(ingreso, n)
            fraccion = 1.0 if completo <= hoy else round(min(meses_completos(inicio, hoy), 12) / 12, 4)
            venc = completo + relativedelta(months=meses_vigencia) - timedelta(days=1)
            res.append(PeriodoCalc(n, inicio, venc, fraccion))
            n += 1
        return res
    return periodos_hasta(ingreso, hoy, al_cumplir_anio, meses_vigencia)


def siguiente_periodo(ingreso: date, numero: int, modo: str, meses_vigencia: int, al_cumplir_anio: bool = True) -> PeriodoCalc:
    """Datos del periodo `numero` aunque aún no empiece (para descontar ahí un saldo negativo)."""
    if modo == "calendario":
        inicio = date(ingreso.year + numero, 1, 1)
        completo = inicio
    elif modo == "mensual":
        inicio, completo = sumar_anios(ingreso, numero - 1), sumar_anios(ingreso, numero)
    else:
        inicio = completo = sumar_anios(ingreso, numero if al_cumplir_anio else numero - 1)
    return PeriodoCalc(numero, inicio, completo + relativedelta(months=meses_vigencia) - timedelta(days=1), 0.0)


@dataclass
class ResultadoValidacion:
    dias_habiles: int
    horas: float
    errores: list[str]
    advertencias: list[str]
    fechas: list[date]

    @property
    def ok(self) -> bool:
        return not self.errores


def validar_vacaciones(
    *,
    cat: str,
    inicio: date,
    fin: date,
    ciclo: Ciclo,
    festivos: set[date],
    horas_disponibles: float,
    periodo_inicio: date,
    periodo_vencimiento: date,
    hoy: date,
    permitir_pasado: bool = False,
    tiene_bloque: bool = False,
    horas_dia: int | None = None,
    bloque_minimo: int | None = None,
    dias_anticipacion: int = 0,
) -> ResultadoValidacion:
    """`tiene_bloque`: el periodo ya tiene una solicitud activa de al menos el mínimo de días seguidos.
    `horas_dia` y `bloque_minimo` vienen del tipo de jornada del empleado (por defecto, los de su categoría)."""
    errores: list[str] = []
    advertencias: list[str] = []
    hd = horas_dia or HORAS_DIA[cat]
    minimo = bloque_minimo or MIN_DIAS_SEGUIDOS[cat]
    cat = hd  # las conversiones de horas a días usan las horas de la jornada

    if fin < inicio:
        return ResultadoValidacion(0, 0, ["La fecha final no puede ser anterior a la inicial."], [], [])

    fechas = dias_laborales(inicio, fin, ciclo, festivos)
    n = len(fechas)
    horas = float(n * hd)

    if n == 0:
        errores.append("El rango seleccionado no contiene días laborales.")
    if not permitir_pasado and inicio < hoy:
        errores.append("No es posible solicitar vacaciones en fechas pasadas.")
    elif not permitir_pasado and dias_anticipacion and inicio < hoy + timedelta(days=dias_anticipacion):
        errores.append(f"Las vacaciones se solicitan con al menos {dias_anticipacion} día(s) de anticipación "
                       f"(a partir del {hoy + timedelta(days=dias_anticipacion):%d/%m/%Y}).")
    if inicio < periodo_inicio:
        errores.append(f"El periodo seleccionado está disponible a partir del {periodo_inicio:%d/%m/%Y}.")
    if fin > periodo_vencimiento:
        errores.append(f"El periodo seleccionado vence el {periodo_vencimiento:%d/%m/%Y}.")

    dias_disponibles_enteros = int(horas_disponibles // hd)
    if n and n < minimo and not tiene_bloque:
        restante_dias = horas_a_dias(horas_disponibles - horas, cat)
        if horas_disponibles < minimo * hd:
            # El saldo ya no alcanza para el bloque: solo se permite tomar todo el remanente de una vez.
            if n != dias_disponibles_enteros:
                errores.append(
                    f"Aún no tomas un bloque de {minimo} días seguidos y tu saldo es menor a {minimo} días; "
                    f"debes tomar los {dias_disponibles_enteros} día(s) restantes juntos."
                )
        elif horas_disponibles - horas < minimo * hd:
            max_sueltos = int((horas_disponibles - minimo * hd) // hd)
            opcion = (f"Puedes pedir como máximo {max_sueltos} día(s) sueltos" if max_sueltos > 0
                      else "Ya no puedes pedir días sueltos")
            errores.append(
                f"En este periodo aún no tomas tus {minimo} días seguidos. Si tomas {n} día(s) te quedarían "
                f"{restante_dias:g} y ya no podrías completarlos. {opcion}, o solicita {minimo} días o más seguidos."
            )
        else:
            advertencias.append(
                f"Recuerda: en este periodo aún debes tomar al menos una vez {minimo} días seguidos "
                f"(te quedarán {restante_dias:g} días)."
            )

    if horas > horas_disponibles + 1e-9:
        errores.append(
            f"Saldo insuficiente: solicitas {n} día(s) ({horas:g} h) y tienes "
            f"{horas_a_dias(horas_disponibles, cat):g} día(s) ({horas_disponibles:g} h)."
        )

    restante = horas_disponibles - horas
    if not errores and 0 < restante < minimo * hd and restante % hd:
        advertencias.append(f"Te quedará un remanente de {restante:g} h que no completa un día.")

    return ResultadoValidacion(n, horas, errores, advertencias, fechas)


def validar_por_horas(*, fecha: date, horas: float, horas_dia: int, minimo_horas: int, bloque_minimo: int,
                      ciclo: Ciclo, festivos: set[date], horas_disponibles: float, periodo_inicio: date,
                      periodo_vencimiento: date, hoy: date, permitir_pasado: bool = False, tiene_bloque: bool = False,
                      dias_anticipacion: int = 0) -> ResultadoValidacion:
    """Vacaciones por horas: parte de una jornada en un solo día laboral."""
    errores: list[str] = []
    advertencias: list[str] = []
    laborales = dias_laborales(fecha, fecha, ciclo, festivos)
    if not laborales:
        errores.append("Ese día no es laboral para el empleado.")
    if horas < minimo_horas:
        errores.append(f"Por horas, el mínimo es {minimo_horas} h.")
    if horas >= horas_dia:
        errores.append(f"Para {horas_dia} h o más, solicita el día completo.")
    if not permitir_pasado and fecha < hoy:
        errores.append("No es posible solicitar vacaciones en fechas pasadas.")
    elif not permitir_pasado and dias_anticipacion and fecha < hoy + timedelta(days=dias_anticipacion):
        errores.append(f"Las vacaciones se solicitan con al menos {dias_anticipacion} día(s) de anticipación.")
    if fecha < periodo_inicio:
        errores.append(f"El periodo seleccionado está disponible a partir del {periodo_inicio:%d/%m/%Y}.")
    if fecha > periodo_vencimiento:
        errores.append(f"El periodo seleccionado vence el {periodo_vencimiento:%d/%m/%Y}.")
    if horas > horas_disponibles + 1e-9:
        errores.append(f"Saldo insuficiente: solicitas {horas:g} h y tienes {max(horas_disponibles, 0):g} h.")
    elif not tiene_bloque and horas_disponibles - horas < bloque_minimo * horas_dia:
        errores.append(f"En este periodo aún no tomas tus {bloque_minimo} días seguidos; si tomas {horas:g} h ya no "
                       "podrías completarlos.")
    return ResultadoValidacion(0, float(horas), errores, advertencias, laborales)


def horas_permiso(hora_inicio: time, hora_fin: time) -> float:
    """Horas entre dos horas del día; si cruza la medianoche se suma un día (turno nocturno)."""
    base = date(2000, 1, 1)
    ini = datetime.combine(base, hora_inicio)
    fin = datetime.combine(base, hora_fin)
    if fin <= ini:
        fin += timedelta(days=1)
    return round((fin - ini).total_seconds() / 3600, 2)
