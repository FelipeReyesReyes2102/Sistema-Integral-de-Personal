"""Calendario general: un jefe solo ve a su equipo; GH ve a todo el personal de su sede; un empleado no tiene acceso."""
from datetime import date

from app.seed import main as seed
from tests.test_consultas import entrar

seed()
HOY = date.today()


def _nombres(cliente):
    r = cliente.get("/api/calendario/equipo", params={"anio": HOY.year, "mes": HOY.month})
    assert r.status_code == 200, r.text
    return r.json(), {e["nombre"] for e in r.json()["empleados"]}


def test_jefe_ve_solo_a_su_equipo():
    datos, nombres = _nombres(entrar("laura@empresa.com"))  # jefa de Carlos y María
    assert {"Carlos Pérez", "María Gómez"} <= nombres
    assert "Ana López" not in nombres and "Laura Martínez" not in nombres
    assert datos["solo_equipo"] is True


def test_gh_ve_a_toda_la_sede():
    datos, nombres = _nombres(entrar("admin@empresa.com", "Admin123"))
    assert {"Ana López", "Carlos Pérez", "María Gómez", "Laura Martínez"} <= nombres
    assert datos["solo_equipo"] is False


def test_empleado_sin_acceso():
    r = entrar("ana@empresa.com").get("/api/calendario/equipo", params={"anio": HOY.year, "mes": HOY.month})
    assert r.status_code == 403
