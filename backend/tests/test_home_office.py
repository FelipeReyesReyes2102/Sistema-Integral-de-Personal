"""Home office: rango de días laborales, aprobación del jefe y aparición en los calendarios."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.seed import main as seed

seed()
FIRMA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def entrar(email, pwd="Cambiar123"):
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"email": email, "password": pwd}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def lunes_en(semanas):
    d = date.today() + timedelta(weeks=semanas)
    return d - timedelta(days=d.weekday())


def test_home_office_completo():
    ana, admin = entrar("ana@empresa.com"), entrar("admin@empresa.com", "Admin123")
    lunes = lunes_en(6)
    datos = {"tipo": "home_office", "fecha": str(lunes), "fecha_fin": str(lunes + timedelta(days=6)),
             "motivo": "Trabajo remoto por proyecto", "enviar": True, "firma": FIRMA}
    r = ana.post("/api/permisos", json=datos)
    assert r.status_code == 201, r.text
    ho = r.json()
    # lunes a domingo: 5 días hábiles menos los festivos de esa semana
    festivos = {f["fecha"] for f in ana.get(f"/api/festivos?anio={lunes.year}").json()}
    esperados = sum(1 for i in range(5) if str(lunes + timedelta(days=i)) not in festivos)
    assert ho["dias"] == esperados and ho["horas"] == 0 and ho["estado"] == "solicitado"
    assert ana.get(f"/api/permisos/{ho['id']}").json()["fecha_fin"] == str(lunes + timedelta(days=6))

    # No se puede encimar con otro home office
    assert ana.post("/api/permisos", json={**datos, "fecha": str(lunes + timedelta(days=2))}).status_code == 422

    # Calendario: un evento por día laboral
    cal = ana.get(f"/api/calendario?anio={lunes.year}").json()
    dias_ho = [p["fecha"] for p in cal["permisos"] if p["id"] == ho["id"]]
    assert len(dias_ho) == esperados or lunes.year != (lunes + timedelta(days=6)).year

    # El jefe (admin) lo aprueba y aparece en el calendario general
    assert admin.post(f"/api/permisos/{ho['id']}/validar", json={}).json()["estado"] == "validado"
    eq = admin.get(f"/api/calendario/equipo?anio={lunes.year}&mes={lunes.month}").json()
    fila = next(e for e in eq["empleados"] if e["nombre"] == "Ana López")
    dias_ho_eq = [f for f, d in fila["dias"].items()
                  if any(e["cat"] == "home_office" and e["estado"] == "validado" for e in d["eventos"])]
    assert dias_ho_eq


def test_home_office_validaciones_y_detalle_vacaciones():
    ana = entrar("ana@empresa.com")
    lunes = lunes_en(9)
    r = ana.post("/api/permisos", json={"tipo": "home_office", "fecha": str(lunes), "fecha_fin": str(lunes - timedelta(days=1))})
    assert r.status_code == 422
    r = ana.post("/api/permisos", json={"tipo": "home_office", "fecha": str(lunes), "fecha_fin": str(lunes + timedelta(days=40))})
    assert r.status_code == 422 and "31 días" in r.text
    # Llegada tarde sigue pidiendo horario
    r = ana.post("/api/permisos", json={"tipo": "llegada_tarde", "fecha": str(lunes)})
    assert r.status_code == 422 and "horario" in r.text
    # Detalle de una solicitud de vacaciones por id
    vs = ana.get("/api/vacaciones").json()
    if vs:
        assert ana.get(f"/api/vacaciones/{vs[0]['id']}").json()["id"] == vs[0]["id"]
