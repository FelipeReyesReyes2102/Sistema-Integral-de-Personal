"""Horario por día y horarios especiales (Short Friday) en los turnos."""
from datetime import date, time, timedelta

from fastapi.testclient import TestClient

from app.horarios import horario_de, resumen
from app.main import app
from app.models import HorarioEspecial, Turno, TurnoDia
from app.seed import main as seed

seed()


def test_horario_por_dia_y_short_friday():
    t = Turno(nombre="Oficina", hora_entrada=time(8, 30), hora_salida=time(17, 0), horas_jornada=8)
    t.dias = [TurnoDia(dia=d, hora_entrada=time(8, 30), hora_salida=time(17, 30)) for d in range(4)] + \
             [TurnoDia(dia=4, hora_entrada=time(8, 30), hora_salida=time(15, 0))]
    assert resumen(t) == "Lun–Jue 08:30–17:30 · Vie 08:30–15:00"
    lunes = date(2026, 10, 12)
    assert horario_de(t, lunes)["salida"] == time(17, 30)
    assert horario_de(t, lunes + timedelta(days=4))["salida"] == time(15, 0)
    # Short Friday cada 2 semanas desde el 16/10 hasta diciembre: viernes de 8:30 a 13:00
    t.especiales = [HorarioEspecial(nombre="Short Friday", fecha_inicio=date(2026, 10, 16), fecha_fin=date(2026, 12, 31),
                                    dias="4", cada_semanas=2, hora_entrada=time(8, 30), hora_salida=time(13, 0), activo=True)]
    v1, v2, v3 = date(2026, 10, 16), date(2026, 10, 23), date(2026, 10, 30)
    assert horario_de(t, v1)["especial"] == "Short Friday" and horario_de(t, v1)["salida"] == time(13, 0)
    assert horario_de(t, v2)["especial"] is None and horario_de(t, v2)["salida"] == time(15, 0)
    assert horario_de(t, v3)["especial"] == "Short Friday"
    assert horario_de(t, date(2027, 1, 8))["especial"] is None  # fuera del rango


def test_api_turno_con_dias_y_especial():
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": "admin@empresa.com", "password": "Admin123"}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    datos = {"nombre": "Oficina Short Friday", "hora_entrada": "08:30", "hora_salida": "17:00", "horas_jornada": 8,
             "dias": [{"dia": d, "hora_entrada": "08:30", "hora_salida": "17:30"} for d in range(4)]
             + [{"dia": 4, "hora_entrada": "08:30", "hora_salida": "15:00"}],
             "especiales": [{"nombre": "Short Friday", "fecha_inicio": "2026-10-16", "dias": [4], "cada_semanas": 2,
                             "hora_entrada": "08:30", "hora_salida": "13:00"}]}
    r = c.post("/api/turnos", json=datos)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["resumen"] == "Lun–Jue 08:30–17:30 · Vie 08:30–15:00" and t["especiales"][0]["dias"] == [4]
    # Editar: quitar el horario por día
    r = c.put(f"/api/turnos/{t['id']}", json={**datos, "dias": []})
    assert r.status_code == 200 and r.json()["resumen"] == "08:30–17:00" and len(r.json()["especiales"]) == 1
    # Validaciones
    malo = {**datos, "especiales": [{**datos["especiales"][0], "fecha_fin": "2026-01-01"}]}
    assert c.post("/api/turnos", json={**malo, "nombre": "X"}).status_code == 422
    # Horario efectivo del propio usuario (su turno de oficina)
    h = c.get("/api/turnos/horario", params={"fecha": "2026-10-16"}).json()
    assert h["turno"] and h["entrada"]
