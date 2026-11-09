"""La salida de equipo ahora es un permiso común: el formato F-630-03 ya no admite solicitudes nuevas."""
from datetime import date, timedelta

from app.seed import main as seed
from tests.test_consultas import entrar

seed()


def test_no_se_crean_salidas_de_equipo():
    ana = entrar("ana@empresa.com")
    f = date.today() + timedelta(days=7)
    r = ana.post("/api/equipos", json={"tipo_equipo": "laptop", "marca": "Dell", "modelo": "X", "serie": "SN-123",
                                      "justificacion": "Prueba", "fecha_inicio": str(f), "fecha_fin": str(f)})
    assert r.status_code == 410 and "Salida de equipo" in r.json()["detail"]
    assert ana.get("/api/pendientes").json().get("equipos", 0) == 0
