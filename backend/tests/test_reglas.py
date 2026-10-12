from datetime import date, time

from app import reglas
from app.reglas import Ciclo, TABLA_ANTIGUEDAD_DEFAULT as T


def test_tabla_antiguedad():
    assert [reglas.dias_por_antiguedad(a, T) for a in (1, 2, 3, 4, 5, 6, 10, 11, 31, 36)] == \
        [12, 14, 16, 18, 20, 22, 22, 24, 32, 32]
    assert reglas.dias_por_antiguedad(37, T) == 34


def test_planta_primer_anio_8_dias():
    horas = reglas.horas_otorgadas(reglas.dias_por_antiguedad(1, T))
    assert horas == 96
    assert reglas.horas_a_dias(horas, "planta") == 8
    assert reglas.horas_a_dias(horas, "oficina") == 12


def test_ciclo_rotativo_4x4():
    c = Ciclo(tipo="rotativo", dias_trabajo=4, dias_descanso=4, fecha_inicio=date(2024, 1, 1))
    patron = [c.es_laboral(date(2024, 1, d)) for d in range(1, 10)]
    assert patron == [True] * 4 + [False] * 4 + [True]


def _validar(cat, inicio, fin, disponibles, ciclo=None, tiene_bloque=False):
    return reglas.validar_vacaciones(
        cat=cat, inicio=inicio, fin=fin, ciclo=ciclo or Ciclo(), festivos=set(),
        horas_disponibles=disponibles, periodo_inicio=date(2024, 1, 1), periodo_vencimiento=date(2025, 6, 30),
        hoy=date(2024, 1, 1), tiene_bloque=tiene_bloque,
    )


def test_oficina_bloque_de_6_dias_al_menos_una_vez():
    # lunes 5 feb a lunes 12 feb = 6 días hábiles (fin de semana no cuenta)
    r = _validar("oficina", date(2024, 2, 5), date(2024, 2, 12), 96)
    assert r.ok and r.dias_habiles == 6 and r.horas == 48
    # Saldo 12 días sin bloque: 5 días sueltos sí (quedan 7, todavía alcanza para los 6 seguidos)
    r = _validar("oficina", date(2024, 2, 5), date(2024, 2, 9), 96)
    assert r.ok and any("6 días seguidos" in a for a in r.advertencias)
    # Ejemplo: quedan 8 días y no ha tomado los 6 seguidos -> 3 días NO (quedarían 5)
    r = _validar("oficina", date(2024, 2, 5), date(2024, 2, 7), 64)
    assert not r.ok and "quedarían 5" in r.errores[0] and "máximo 2" in r.errores[0]
    # ... pero 2 días sí (quedan 6)
    assert _validar("oficina", date(2024, 2, 5), date(2024, 2, 6), 64).ok
    # Si ya tomó (o solicitó) su bloque de 6, puede tomar días sueltos sin restricción
    assert _validar("oficina", date(2024, 2, 5), date(2024, 2, 7), 64, tiene_bloque=True).ok


def test_planta_minimo_4_dias_en_su_ciclo():
    c = Ciclo(tipo="rotativo", dias_trabajo=4, dias_descanso=4, fecha_inicio=date(2024, 1, 1))
    r = _validar("planta", date(2024, 1, 9), date(2024, 1, 11), 60, c)  # 3 días con 5 de saldo: quedaría 2 < 4
    assert not r.ok
    assert _validar("planta", date(2024, 1, 9), date(2024, 1, 11), 96, c).ok  # con 8 días de saldo quedan 5
    r = _validar("planta", date(2024, 1, 9), date(2024, 1, 20), 96, c)  # 9-12 trabaja, 13-16 descansa, 17-20 trabaja
    assert r.ok and r.dias_habiles == 8 and r.horas == 96


def test_saldo_insuficiente_y_remanente():
    r = _validar("oficina", date(2024, 2, 5), date(2024, 2, 16), 48)  # 10 días, solo 6 disponibles
    assert not r.ok and any("Saldo insuficiente" in e for e in r.errores)
    # Saldo de 3 días (< 6) sin bloque: solo se permite tomar los 3 restantes juntos
    assert _validar("oficina", date(2024, 2, 5), date(2024, 2, 7), 24).ok
    assert not _validar("oficina", date(2024, 2, 5), date(2024, 2, 6), 24).ok


def test_horas_permiso_turno_nocturno():
    assert reglas.horas_permiso(time(8), time(10, 30)) == 2.5
    assert reglas.horas_permiso(time(23), time(1)) == 2


def test_vigencia_18_meses_y_perdida():
    ps = reglas.periodos_hasta(date(2020, 3, 1), date(2024, 3, 15), True, 18)
    # El periodo 1 se otorga el 01/03/2021 y vence 18 meses después
    assert ps[0].fecha_inicio == date(2021, 3, 1) and ps[0].fecha_vencimiento == date(2022, 8, 31)
    assert reglas.horas_perdidas(40, date(2022, 8, 31), date(2022, 8, 31)) == 0   # último día aún vigente
    assert reglas.horas_perdidas(40, date(2022, 8, 31), date(2022, 9, 1)) == 40   # al día siguiente se pierde
    assert reglas.horas_perdidas(-8, date(2022, 8, 31), date(2023, 1, 1)) == 0
