"""Super administrador: acceso total, protección del rol y acceso con número de nómina."""
from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Usuario
from app.security import hash_password
from app.seed import main as seed

seed()


def crear_super(email="root@empresa.com", nomina="SA-100"):
    with SessionLocal() as db:
        if not db.query(Usuario).filter(Usuario.email == email).first():
            db.add(Usuario(numero_empleado=nomina, nombre="Root", email=email, rol="superadmin",
                           password_hash=hash_password("Root12345"), fecha_ingreso=date(2020, 1, 1)))
            db.commit()


def entrar(usuario, pwd):
    c = TestClient(app)
    r = c.post("/api/auth/login-json", json={"usuario": usuario, "password": pwd})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def nuevo(rol, nomina, email):
    return {"numero_empleado": nomina, "nombre": f"Usuario {nomina}", "email": email, "rol": rol,
            "fecha_ingreso": "2022-01-10", "password": "Clave12345"}


def test_login_con_correo_o_numero_de_nomina():
    assert entrar("ana@empresa.com", "Cambiar123").get("/api/auth/me").json()["numero_empleado"] == "1001"
    assert entrar("1001", "Cambiar123").get("/api/auth/me").json()["email"] == "ana@empresa.com"
    r = TestClient(app).post("/api/auth/login-json", json={"usuario": "1001", "password": "mala"})
    assert r.status_code == 401
    # Compatibilidad con el campo anterior
    assert TestClient(app).post("/api/auth/login-json", json={"email": "ana@empresa.com", "password": "Cambiar123"}).status_code == 200


def test_super_admin_acceso_total_y_proteccion_del_rol():
    crear_super()
    root = entrar("SA-100", "Root12345")
    me = root.get("/api/auth/me").json()
    assert me["rol"] == "superadmin" and "config:microsoft" in me["permissions"] and "usuarios:administrar" in me["permissions"]
    # Todo lo del administrador
    assert root.get("/api/usuarios").status_code == 200
    assert root.get(f"/api/calendario/equipo?anio={date.today().year}&mes=1").status_code == 200
    assert root.get("/api/admin/config/microsoft").status_code == 200

    admin = entrar("admin@empresa.com", "Admin123")
    # El administrador ya no ve la configuración de Microsoft
    assert admin.get("/api/admin/config/microsoft").status_code == 403
    # ...ni puede crear super administradores
    r = admin.post("/api/usuarios", json=nuevo("superadmin", "SA-200", "sa200@empresa.com"))
    assert r.status_code == 403 and "super administrador" in r.text
    # ...ni promoverse a sí mismo
    yo = admin.get("/api/auth/me").json()
    datos = {k: yo[k] for k in ("numero_empleado", "nombre", "email", "fecha_ingreso", "es_jefe", "activo")}
    assert admin.put(f"/api/usuarios/{yo['id']}", json={**datos, "rol": "superadmin"}).status_code == 403
    # ...ni modificar o desactivar a un super administrador
    sa = next(u for u in admin.get("/api/usuarios").json() if u["email"] == "root@empresa.com")
    assert admin.put(f"/api/usuarios/{sa['id']}", json={**nuevo("superadmin", "SA-100", "root@empresa.com"), "nombre": "X"}).status_code == 403
    assert admin.delete(f"/api/usuarios/{sa['id']}").status_code == 403

    # Un super administrador sí puede crear a otro
    r = root.post("/api/usuarios", json=nuevo("superadmin", "SA-300", "sa300@empresa.com"))
    assert r.status_code == 201, r.text


def test_siempre_queda_un_super_admin():
    crear_super("solo@empresa.com", "SA-900")
    with SessionLocal() as db:  # dejar solo uno activo
        for u in db.query(Usuario).filter(Usuario.rol == "superadmin", Usuario.email != "solo@empresa.com"):
            u.activo = False
        db.commit()
    yo = entrar("solo@empresa.com", "Root12345")
    me = yo.get("/api/auth/me").json()
    datos = {k: me[k] for k in ("numero_empleado", "nombre", "email", "fecha_ingreso", "es_jefe", "activo")}
    r = yo.put(f"/api/usuarios/{me['id']}", json={**datos, "rol": "admin"})
    assert r.status_code == 400 and "al menos un super administrador" in r.text


def test_correo_corporativo_y_personal():
    admin = entrar("admin@empresa.com", "Admin123")
    # Oficinas: el correo corporativo es obligatorio
    r = admin.post("/api/usuarios", json={**nuevo("oficina", "C-1", None), "email_personal": "c1@gmail.com"})
    assert r.status_code == 422 and "corporativo es obligatorio" in r.text
    r = admin.post("/api/usuarios", json={**nuevo("oficina", "C-1", "C1@O-tek.com"), "email_personal": "c1@gmail.com"})
    assert r.status_code == 201 and r.json()["email"] == "c1@o-tek.com" and r.json()["email_personal"] == "c1@gmail.com"
    # Planta: no tiene correo corporativo aunque se envíe; solo personal
    r = admin.post("/api/usuarios", json={**nuevo("planta", "P-1", "p1@o-tek.com"), "email_personal": "p1@gmail.com"})
    assert r.status_code == 201 and r.json()["email"] is None and r.json()["email_personal"] == "p1@gmail.com"
    r = admin.post("/api/usuarios", json={**nuevo("planta", "P-2", None)})  # planta sin ningún correo: permitido
    assert r.status_code == 201
    assert admin.post("/api/usuarios", json={**nuevo("planta", "P-3", None), "email_personal": "malo"}).status_code == 422
    # Se puede entrar con el correo personal, el corporativo o la nómina
    assert entrar("p1@gmail.com", "Clave12345").get("/api/auth/me").json()["numero_empleado"] == "P-1"
    assert entrar("c1@gmail.com", "Clave12345").get("/api/auth/me").json()["numero_empleado"] == "C-1"
    assert entrar("c1@o-tek.com", "Clave12345").get("/api/auth/me").json()["numero_empleado"] == "C-1"
