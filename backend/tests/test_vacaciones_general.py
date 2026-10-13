"""Modo general: el saldo es la suma de los periodos vigentes y se descuenta primero del periodo más antiguo."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.seed import main as seed

seed()
FIRMA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def admin():
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": "admin@empresa.com", "password": "Admin123"}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def test_general_reparte_entre_periodos_empezando_por_el_anterior():
    adm = admin()
    hoy = date.today()
    # Ingreso hace 2 años y 2 meses: el periodo del año 1 sigue vigente (18 meses) y el del año 2 ya empezó
    ingreso = date(hoy.year - 2, hoy.month, 1) - timedelta(days=62)
    u = adm.post("/api/usuarios", json={"numero_empleado": "G-100", "nombre": "Empleado General", "rol": "oficina",
                                       "email": "general@o-tek.com", "fecha_ingreso": ingreso.isoformat()}).json()
    periodos = [p for p in adm.get(f"/api/periodos?usuario_id={u['id']}").json() if p["vigente"] and p["dias_disponible"] > 0]
    assert len(periodos) == 2
    viejo, nuevo = sorted(periodos, key=lambda p: p["fecha_inicio"])
    cap = int(viejo["dias_disponible"])

    # Rango que empieza el próximo lunes y suma cap + 2 días laborales
    inicio = hoy + timedelta(days=7 - hoy.weekday())
    fin = inicio
    while adm.post("/api/vacaciones/dias-laborales", json={"fecha_inicio": inicio.isoformat(), "fecha_fin": fin.isoformat(),
                                                         "usuario_id": u["id"]}).json()["dias_habiles"] < cap + 2:
        fin += timedelta(days=1)
    rango = {"fecha_inicio": inicio.isoformat(), "fecha_fin": fin.isoformat(), "usuario_id": u["id"]}

    c = adm.post("/api/vacaciones/calcular", json=rango).json()
    assert c["errores"] == [], c
    assert c["dias_habiles"] == cap + 2
    # Solo cuentan los periodos vigentes en el rango (no los vencidos), también para el administrador
    assert round(c["dias_disponible"]) == round(viejo["dias_disponible"] + nuevo["dias_disponible"])
    assert [(t["periodo_id"], t["dias"]) for t in c["reparto"]] == [(viejo["id"], cap), (nuevo["id"], 2)]

    jefe_id = adm.get("/api/auth/me").json()["id"]
    r = adm.post("/api/vacaciones", json={**rango, "enviar": True, "firma": FIRMA, "comentario": "Viaje", "aprobador_id": jefe_id})
    assert r.status_code == 201, r.text
    sols = sorted(adm.get(f"/api/vacaciones?usuario_id={u['id']}").json(), key=lambda s: s["fecha_inicio"])
    assert [(s["periodo_id"], s["dias_habiles"], s["estado"]) for s in sols] == [
        (viejo["id"], cap, "solicitado"), (nuevo["id"], 2, "solicitado")]
    assert sols[0]["comentario"] == "[Parte 1 de 2] Viaje" and sols[1]["comentario"] == "[Parte 2 de 2] Viaje"

    # Pedir más días de los que hay entre ambos periodos no se permite
    lejos = fin + timedelta(days=30)
    r = adm.post("/api/vacaciones/calcular", json={"fecha_inicio": lejos.isoformat(),
                                                   "fecha_fin": (lejos + timedelta(days=60)).isoformat(), "usuario_id": u["id"]})
    assert any("Saldo insuficiente" in e for e in r.json()["errores"])
