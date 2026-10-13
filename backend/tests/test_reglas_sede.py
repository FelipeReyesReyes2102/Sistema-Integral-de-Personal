"""Tabla de días por antigüedad por sede."""
from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import ReglaAntiguedad, Sede, Usuario
from app.security import hash_password
from app.seed import main as seed

seed()


def entrar(usuario, pwd, sede=None):
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": usuario, "password": pwd}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    if sede:
        c.headers["X-Sede-Id"] = str(sede)
    return c


def test_tabla_propia_por_sede():
    with SessionLocal() as db:
        cart = db.query(Sede).filter(Sede.nombre == "Cartagena (reglas)").first()
        if cart is None:
            cart = Sede(nombre="Cartagena (reglas)", zona_horaria="America/Bogota")
            db.add(cart)
            db.commit()
        if not db.query(Usuario).filter(Usuario.numero_empleado == "CR-1").first():
            db.add_all([
                Usuario(numero_empleado="CR-1", nombre="Admin Cartagena", email="admin.cr@o-tek.com", rol="admin",
                        password_hash=hash_password("Clave12345"), fecha_ingreso=date(2020, 1, 1), sede_id=cart.id),
                Usuario(numero_empleado="CR-2", nombre="Empleado Cartagena", email="emp.cr@o-tek.com", rol="oficina",
                        password_hash=hash_password("Clave12345"), fecha_ingreso=date(date.today().year - 1, 1, 2),
                        sede_id=cart.id),
            ])
            db.commit()
        cid = cart.id
    adm = entrar("admin.cr@o-tek.com", "Clave12345")
    t = adm.get("/api/reglas-antiguedad").json()
    assert t["sede_nombre"] == "Cartagena (reglas)" and t["propia"] is False and t["reglas"][0]["dias"] == 12
    emp = entrar("emp.cr@o-tek.com", "Clave12345")
    assert emp.get("/api/periodos").json()[0]["dias_ley"] == 12  # usa la tabla de México

    # Colombia: 15 días hábiles desde el primer año
    r = adm.put("/api/reglas-antiguedad", json=[{"anios_desde": 1, "anios_hasta": 50, "dias": 15}])
    assert r.status_code == 200 and r.json()["propia"] is True
    assert emp.get("/api/periodos").json()[0]["dias_ley"] == 15
    # México no cambia
    mx = entrar("admin@empresa.com", "Admin123")
    assert mx.get("/api/reglas-antiguedad").json()["reglas"][0]["dias"] == 12
    assert entrar("ana@empresa.com", "Cambiar123").get("/api/periodos").json()[0]["dias_ley"] != 15
    # Un administrador no modifica la tabla de otra sede (el selector se ignora)
    mx_cr = entrar("admin@empresa.com", "Admin123", sede=cid)
    assert mx_cr.get("/api/reglas-antiguedad").json()["sede_nombre"] == "O-tek México"
    # Volver a la tabla de México
    assert adm.delete("/api/reglas-antiguedad").json()["propia"] is False
    assert emp.get("/api/periodos").json()[0]["dias_ley"] == 12
    assert mx.delete("/api/reglas-antiguedad").status_code == 400  # la principal siempre tiene la suya
    with SessionLocal() as db:
        assert db.query(ReglaAntiguedad).filter(ReglaAntiguedad.sede_id == cid).count() == 0
