"""Cada 6 meses (desde el registro o el último cambio) el usuario debe confirmar o actualizar sus datos personales."""
from datetime import timedelta

from app.database import SessionLocal
from app.models import Usuario
from app.security import ahora
from app.seed import main as seed
from tests.test_consultas import entrar

seed()


def _fecha(email, creado=None, confirmados=None):
    with SessionLocal() as db:
        u = db.query(Usuario).filter(Usuario.email == email).one()
        if creado:
            u.creado = creado
        u.datos_confirmados = confirmados
        db.commit()


def test_confirmar_datos_cada_seis_meses():
    email = "ana@empresa.com"
    _fecha(email, creado=ahora() - timedelta(days=30))
    c = entrar(email)
    me = c.get("/api/auth/me").json()
    assert me["debe_confirmar_datos"] is False and me["proxima_confirmacion"]

    # Pasados 6 meses del registro se le pide confirmar y no puede guardar otra cosa
    _fecha(email, creado=ahora() - timedelta(days=190))
    assert c.get("/api/auth/me").json()["debe_confirmar_datos"] is True
    r = c.post("/api/vacaciones/calcular", json={"fecha_inicio": "2030-01-07", "fecha_fin": "2030-01-07"})
    assert r.status_code == 403 and "datos personales" in r.json()["detail"]
    assert c.get("/api/periodos").status_code == 200  # consultar sí

    # Validaciones y guardado: reinicia el conteo
    assert c.put("/api/auth/mis-datos", json={"telefono": "xx"}).status_code == 422
    assert c.put("/api/auth/mis-datos", json={"email_personal": "admin@empresa.com"}).status_code == 409
    r = c.put("/api/auth/mis-datos", json={"telefono": "55 1111 2222", "direccion": "Calle 1 #2, Monterrey",
                                           "contacto_nombre": "José (papá)", "contacto_telefono": "81 3333 4444"})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["debe_confirmar_datos"] is False and me["telefono"] == "55 1111 2222" and me["datos_confirmados"]
    assert c.post("/api/vacaciones/calcular", json={"fecha_inicio": "2030-01-07", "fecha_fin": "2030-01-07"}).status_code == 200

    # 6 meses después del último cambio se vuelve a pedir; confirmar sin cambios también reinicia
    _fecha(email, confirmados=ahora() - timedelta(days=185))
    assert c.get("/api/auth/me").json()["debe_confirmar_datos"] is True
    datos = {k: me[k] for k in ("email_personal", "fecha_nacimiento", "telefono", "direccion", "contacto_nombre", "contacto_telefono")}
    assert c.put("/api/auth/mis-datos", json=datos).json()["debe_confirmar_datos"] is False
    _fecha(email, creado=ahora())
