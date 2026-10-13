"""Cumpleaños: se capturan en el empleado y todos los ven en el calendario (solo día y mes)."""
from fastapi.testclient import TestClient

from app.main import app
from app.seed import main as seed

seed()


def entrar(usuario, password):
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": usuario, "password": password}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def test_cumpleanos_visibles_para_todos_sin_anio():
    adm = entrar("admin@empresa.com", "Admin123")
    r = adm.post("/api/usuarios", json={"numero_empleado": "C-100", "nombre": "Cumple Prueba", "rol": "oficina",
                                       "email": "cumple@o-tek.com", "fecha_ingreso": "2020-01-15",
                                       "fecha_nacimiento": "1992-02-29"})
    assert r.status_code == 201, r.text
    assert r.json()["fecha_nacimiento"] == "1992-02-29"

    # Cualquier empleado lo ve en su calendario, con la fecha del año consultado y sin el año de nacimiento
    cal = adm.get("/api/calendario?anio=2027").json()
    c = next(x for x in cal["cumpleanos"] if x["nombre"] == "Cumple Prueba")
    assert c["fecha"] == "2027-02-28"  # 29 de febrero en año no bisiesto
    assert "1992" not in str(c)
    assert next(x for x in adm.get("/api/calendario?anio=2028").json()["cumpleanos"] if x["nombre"] == "Cumple Prueba")["fecha"] == "2028-02-29"

    # Si se desactiva el empleado deja de aparecer
    adm.delete(f"/api/usuarios/{r.json()['id']}")
    assert not any(x["nombre"] == "Cumple Prueba" for x in adm.get("/api/calendario?anio=2027").json()["cumpleanos"])
