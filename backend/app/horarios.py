"""Horario efectivo de un turno en una fecha: horario especial (p. ej. Short Friday) > horario del día > general."""
from datetime import date, time, timedelta

from . import reglas
from .models import HorarioEspecial, Turno

DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def dias_de(especial: HorarioEspecial) -> set[int]:
    return {int(x) for x in (especial.dias or "").split(",") if x.strip().isdigit()}


def aplica(especial: HorarioEspecial, fecha: date) -> bool:
    if not especial.activo or fecha < especial.fecha_inicio or (especial.fecha_fin and fecha > especial.fecha_fin):
        return False
    if fecha.weekday() not in dias_de(especial):
        return False
    # Cada N semanas, contando desde la semana (lunes) en que inicia
    inicio = especial.fecha_inicio - timedelta(days=especial.fecha_inicio.weekday())
    return ((fecha - inicio).days // 7) % max(especial.cada_semanas or 1, 1) == 0


def horario_de(turno: Turno | None, fecha: date) -> dict | None:
    """{entrada, salida, horas, especial} del turno en esa fecha."""
    if turno is None:
        return None
    entrada, salida, especial = turno.hora_entrada, turno.hora_salida, None
    for d in turno.dias:
        if d.dia == fecha.weekday():
            entrada, salida = d.hora_entrada, d.hora_salida
    for e in turno.especiales:
        if aplica(e, fecha):
            entrada, salida, especial = e.hora_entrada, e.hora_salida, e.nombre
            break
    return {"entrada": entrada, "salida": salida, "horas": reglas.horas_permiso(entrada, salida), "especial": especial}


def _txt(t: time) -> str:
    return t.strftime("%H:%M")


def resumen(turno: Turno) -> str:
    """Horario semanal agrupando días iguales, p. ej. "Lun–Jue 08:30–17:30 · Vie 08:30–15:00"."""
    propios = {d.dia: (d.hora_entrada, d.hora_salida) for d in turno.dias}
    if not propios:
        return f"{_txt(turno.hora_entrada)}–{_txt(turno.hora_salida)}"
    general = (turno.hora_entrada, turno.hora_salida)
    dias = [d for d in range(7) if d < 5 or d in propios]  # fin de semana solo si tiene horario propio
    grupos: list[list] = []
    for d in dias:
        h = propios.get(d, general)
        if grupos and grupos[-1][2] == h and grupos[-1][1] == d - 1:
            grupos[-1][1] = d
        else:
            grupos.append([d, d, h])
    partes = []
    for ini, fin, (e, s) in grupos:
        rango = DIAS_CORTOS[ini] if ini == fin else f"{DIAS_CORTOS[ini]}–{DIAS_CORTOS[fin]}"
        partes.append(f"{rango} {_txt(e)}–{_txt(s)}")
    return " · ".join(partes)


def semana(turno: Turno | None, lunes: date) -> list[dict]:
    """Horario de cada día de la semana que inicia en `lunes`."""
    res = []
    for i in range(7):
        f = lunes + timedelta(days=i)
        h = horario_de(turno, f)
        res.append({"fecha": f, "dia": DIAS_CORTOS[i],
                    "entrada": _txt(h["entrada"]) if h else None, "salida": _txt(h["salida"]) if h else None,
                    "especial": h["especial"] if h else None})
    return res
