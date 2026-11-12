"""Catálogo fijo de departamentos: validación, equivalencias y migración de los nombres anteriores."""
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.departamentos import DEPARTAMENTOS, normalizar
from app.migraciones import _normalizar_departamentos
from app.models import Usuario
from app.schemas import PermisoIn, UsuarioIn
from app.seed import main as seed
from tests.test_consultas import entrar

seed()


def test_normalizar_equivalencias():
    assert normalizar("Cadena De Suministros") == "Logística"
    assert normalizar("cadena suministro") == "Logística"
    assert normalizar("Operaciones") == "Producción"
    assert normalizar("IT") == "Sistemas"
    assert normalizar("Gestión Humana") == "GH"
    assert normalizar("Contabilidad") == "Finanzas"
    assert normalizar("logistica") == "Logística"
    assert normalizar("  ") is None and normalizar("Marketing") is None


def test_esquemas_aceptan_solo_el_catalogo():
    base = {"numero_empleado": "X-1", "nombre": "X", "fecha_ingreso": "2024-01-01"}
    assert UsuarioIn(**base, departamento="ingenieria").departamento == "Ingeniería"
    assert UsuarioIn(**base, departamento="").departamento is None
    try:
        UsuarioIn(**base, departamento="Marketing")
        assert False, "debió rechazarse"
    except ValueError as e:
        assert "no es válido" in str(e)
    assert PermisoIn(tipo="llegada_tarde", fecha="2026-01-05", departamento="IT").departamento == "Sistemas"


def test_endpoint_devuelve_catalogo():
    h = entrar("ana@empresa.com")
    r = h.get("/api/departamentos")
    assert r.status_code == 200 and r.json() == DEPARTAMENTOS


def test_migracion_pasa_nombres_anteriores():
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.departamento.is_not(None)).first()
        original = u.departamento
        u.departamento = "Cadena De Suministros"
        db.commit()
        uid = u.id
    with engine.begin() as conn:
        _normalizar_departamentos(conn)
        _normalizar_departamentos(conn)  # idempotente
    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        assert u.departamento == "Logística"
        u.departamento = original
        db.commit()
