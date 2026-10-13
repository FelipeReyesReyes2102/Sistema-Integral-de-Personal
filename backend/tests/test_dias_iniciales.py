"""Saldo capturado al crear o editar un empleado: primero el periodo actual y el resto en el anterior."""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.seed import main as seed

seed()


def admin():
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": "admin@empresa.com", "password": "Admin123"}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def saldos(adm, uid):
    ps = [p for p in adm.get(f"/api/periodos?usuario_id={uid}").json() if p["vigente"]]
    return {p["numero"]: p["dias_disponible"] for p in ps}


def test_dias_disponibles_llenan_primero_el_periodo_actual():
    adm = admin()
    hoy = date.today()
    # 2 años cumplidos hace un mes: periodo 1 (12 días) aún vigente y periodo 2 (14 días) actual
    ingreso = date(hoy.year - 2, hoy.month, 1)
    ingreso = ingreso.replace(month=ingreso.month - 1) if ingreso.month > 1 else ingreso.replace(year=ingreso.year - 1, month=12)
    datos = {"numero_empleado": "D-100", "nombre": "Saldo Inicial", "rol": "oficina", "email": "saldo@o-tek.com",
             "fecha_ingreso": ingreso.isoformat(), "dias_disponibles": 18}
    r = adm.post("/api/usuarios", json=datos)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert saldos(adm, uid) == {1: 4, 2: 14}

    # Al editar se puede corregir
    r = adm.put(f"/api/usuarios/{uid}", json={**datos, "dias_disponibles": 10})
    assert r.status_code == 200, r.text
    assert saldos(adm, uid) == {1: 0, 2: 10}

    # Sin el campo no se toca el saldo
    datos.pop("dias_disponibles")
    adm.put(f"/api/usuarios/{uid}", json={**datos, "puesto": "Analista"})
    assert saldos(adm, uid) == {1: 0, 2: 10}

    # Más de lo que permiten los periodos vigentes: error y no se crea el usuario
    r = adm.post("/api/usuarios", json={**datos, "numero_empleado": "D-101", "email": "saldo2@o-tek.com", "dias_disponibles": 40})
    assert r.status_code == 422 and "máximo 26" in r.json()["detail"]
    assert not any(u["numero_empleado"] == "D-101" for u in adm.get("/api/usuarios").json())
