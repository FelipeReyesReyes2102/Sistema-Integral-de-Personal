"""Contraseña temporal de 6 dígitos: cambio obligatorio, vencimiento, bloqueo por intentos y restablecimiento."""
from datetime import timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Usuario
from app.security import ahora
from app.seed import main as seed

seed()


def admin():
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": "admin@empresa.com", "password": "Admin123"}).status_code == 200
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def alta(adm, nomina, rol="planta"):
    datos = {"numero_empleado": nomina, "nombre": f"Empleado {nomina}", "rol": rol, "fecha_ingreso": "2023-03-01",
             "email": f"{nomina.lower()}@o-tek.com" if rol != "planta" else None}
    r = adm.post("/api/usuarios", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def entrar(usuario, pwd):
    c = TestClient(app)
    r = c.post("/api/auth/login-json", json={"usuario": usuario, "password": pwd})
    if r.status_code == 200:
        c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c, r


def test_alta_genera_6_digitos_y_obliga_a_cambiar():
    adm = admin()
    u = alta(adm, "T-100")
    t = u["password_temporal"]
    assert t and len(t) == 6 and t.isdigit() and u["debe_cambiar_password"] and u["password_temporal_expira"]
    # La contraseña temporal no se vuelve a mostrar al consultar el usuario
    assert adm.get(f"/api/usuarios/{u['id']}").json()["password_temporal"] is None

    c, r = entrar("T-100", t)
    assert r.status_code == 200 and r.json()["debe_cambiar_password"] is True
    # Mientras no cambie la contraseña, solo puede ver su perfil y cambiarla
    assert c.get("/api/auth/me").status_code == 200
    r = c.get("/api/periodos")
    assert r.status_code == 403 and "contraseña temporal" in r.json()["detail"]
    # Reglas de la contraseña nueva
    assert c.post("/api/auth/cambiar-password", json={"actual": t, "nueva": "corta1"}).status_code == 422
    assert c.post("/api/auth/cambiar-password", json={"actual": t, "nueva": "soloLetrasAqui"}).status_code == 422
    assert c.post("/api/auth/cambiar-password", json={"actual": t, "nueva": "Planta2026x"}).status_code == 204
    assert c.get("/api/auth/me").json()["debe_cambiar_password"] is False
    assert c.get("/api/periodos").status_code == 200
    # La temporal ya no sirve; la nueva sí
    assert entrar("T-100", t)[1].status_code == 401
    assert entrar("T-100", "Planta2026x")[1].status_code == 200


def test_bloqueo_por_intentos_y_restablecer():
    adm = admin()
    u = alta(adm, "T-200")
    t = u["password_temporal"]
    for _ in range(5):
        assert entrar("T-200", "000000" if t != "000000" else "111111")[1].status_code == 401
    r = entrar("T-200", t)[1]
    assert r.status_code == 423 and "bloqueado" in r.json()["detail"]
    assert next(x for x in adm.get("/api/usuarios").json() if x["id"] == u["id"])["bloqueado"] is True
    # El administrador restablece: nueva temporal, desbloqueado
    nueva = adm.post(f"/api/usuarios/{u['id']}/password-temporal").json()["password_temporal"]
    assert len(nueva) == 6 and entrar("T-200", nueva)[1].status_code == 200


def test_temporal_vencida_y_oficinas():
    adm = admin()
    u = alta(adm, "T-300", rol="oficina")
    assert len(u["password_temporal"]) == 6   # oficinas también recibe temporal mientras el acceso con contraseña esté permitido
    with SessionLocal() as db:
        db.get(Usuario, u["id"]).password_temporal_expira = ahora() - timedelta(minutes=1)
        db.commit()
    r = entrar("t-300@o-tek.com", u["password_temporal"])[1]
    assert r.status_code == 401 and "venció" in r.json()["detail"]
    # Un administrador no puede restablecer la contraseña de un super administrador
    with SessionLocal() as db:
        sa = db.query(Usuario).filter(Usuario.rol == "superadmin").first()
        sa_id = sa.id if sa else None
    if sa_id:
        assert adm.post(f"/api/usuarios/{sa_id}/password-temporal").status_code == 403
