"""Administrador (solo Ajustes de su sede), acceso a manuales por tipo de usuario y cifrado de consultas anteriores."""
from datetime import date

from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models import Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.seed import main as seed
from tests.test_consultas import entrar

seed()


def _administrador():
    with SessionLocal() as db:
        if not db.query(Usuario).filter(Usuario.email == "config@o-tek.com").first():
            db.add(Usuario(numero_empleado="ADM-1", nombre="Admin Configuración", email="config@o-tek.com",
                           rol="administrador", password_hash=hash_password("Config123x"), fecha_ingreso=date(2021, 1, 4),
                           sede_id=sede_principal(db).id))
            db.commit()
    return entrar("config@o-tek.com", "Config123x")


def test_administrador_solo_ajustes():
    adm = _administrador()
    anio = date.today().year + 2
    r = adm.post("/api/festivos", json={"fecha": f"{anio}-07-15", "nombre": "Festivo de prueba", "aplica_a": "todos"})
    assert r.status_code == 201, r.text
    assert adm.delete(f"/api/festivos/{r.json()['id']}").status_code == 204
    assert adm.get("/api/tipos-permiso").status_code == 200
    assert adm.get("/api/rotacion").status_code == 200
    usuarios = adm.get("/api/usuarios").json()
    assert usuarios and all(u["email"] is None and u.get("saldo_dias") is None for u in usuarios)
    # No es GH: ni empleados (alta), ni solicitudes, ni bitácora, ni super administrador
    assert adm.post("/api/usuarios", json={"numero_empleado": "X-1", "nombre": "X", "rol": "oficina",
                                          "fecha_ingreso": "2024-01-01"}).status_code == 403
    assert adm.get("/api/bitacora").status_code == 403
    assert adm.get("/api/sharepoint").status_code == 403
    assert adm.get("/api/calendario/equipo", params={"anio": anio, "mes": 1}).status_code == 403


def test_manuales_por_tipo_de_usuario():
    casos = {
        ("ana@empresa.com", "Cambiar123"): {"empleado"},
        ("laura@empresa.com", "Cambiar123"): {"empleado", "jefe"},
        ("admin@empresa.com", "Admin123"): {"empleado", "jefe", "gh"},
        ("medico@empresa.com", "Cambiar123"): {"servicio-medico"},
        ("config@o-tek.com", "Config123x"): {"empleado", "gh"},
    }
    _administrador()
    for (correo, pwd), esperados in casos.items():
        d = entrar(correo, pwd).get("/api/manuales").json()
        assert {m[7:-5] for m in d["manuales"]} == esperados, correo
        assert len(d["presentaciones"]) == len(esperados)


def test_cifra_consultas_anteriores():
    from app.migraciones import _cifrar_consultas
    from app.models import ConsultaMedica
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.email == "ana@empresa.com").one()
        c = ConsultaMedica(paciente_id=u.id, fecha=date(2020, 1, 2), hora_inicio=__import__("datetime").time(9),
                           sintomas="temporal", resultado="regresa_labores")
        db.add(c)
        db.commit()
        cid = c.id
    with engine.begin() as conn:  # simula un registro guardado antes del cifrado
        conn.execute(text("UPDATE consultas_medicas SET sintomas = 'Tos seca', diagnostico = 'Gripe' WHERE id = :i"), {"i": cid})
    with engine.begin() as conn:
        _cifrar_consultas(conn)
        _cifrar_consultas(conn)  # idempotente
        crudo = conn.execute(text("SELECT sintomas, diagnostico FROM consultas_medicas WHERE id = :i"), {"i": cid}).one()
    assert crudo.sintomas.startswith("enc1:") and crudo.diagnostico.startswith("enc1:")
    with SessionLocal() as db:
        c = db.get(ConsultaMedica, cid)
        assert c.sintomas == "Tos seca" and c.diagnostico == "Gripe"
        db.delete(c)
        db.commit()


def test_nomina_vacia_no_se_acepta():
    adm = entrar("admin@empresa.com", "Admin123")
    r = adm.post("/api/usuarios", json={"numero_empleado": "  ", "nombre": "Caseta Prueba", "rol": "caseta",
                                       "email_personal": "caseta.prueba@example.com", "fecha_ingreso": "2026-11-10"})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "numero_empleado"
    assert "obligatorio" in r.json()["detail"][0]["msg"]
