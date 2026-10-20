"""Servicio médico: el médico registra consultas; el paciente las ve completas; jefe/admin solo el resumen."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.seed import main as seed

seed()


def entrar(email, pwd="Cambiar123"):
    c = TestClient(app)
    r = c.post("/api/auth/login-json", json={"email": email, "password": pwd})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def test_flujo_consulta_medica():
    medico = entrar("medico@empresa.com")
    me = medico.get("/api/auth/me").json()
    assert me["rol"] == "medico" and "consultas:registrar" in me["permissions"]

    # Filtrar pacientes por tipo de usuario
    planta = medico.get("/api/consultas/pacientes?rol=planta").json()
    assert planta and all(p["rol"] == "planta" for p in planta)
    carlos = next(p for p in planta if p["nombre"] == "Carlos Pérez")
    assert medico.get("/api/consultas/pacientes?rol=planta&q=Carlos").json()[0]["id"] == carlos["id"]

    r = medico.post("/api/consultas", json={
        "paciente_id": carlos["id"], "fecha": str(date.today()), "hora_inicio": "10:00", "hora_fin": "10:40",
        "sintomas": "Dolor de cabeza y mareo", "diagnostico": "Migraña", "indicaciones": "Reposo 30 min",
        "resultado": "regresa_labores",
        "medicamentos": [{"nombre": "Paracetamol", "dosis": "500 mg", "frecuencia": "cada 8 h", "duracion": "2 días"}]})
    assert r.status_code == 201, r.text
    consulta = r.json()
    assert consulta["medicamentos"][0]["nombre"] == "Paracetamol" and consulta["medico_nombre"] == "Dra. Patricia Ruiz"

    # El paciente ve la consulta completa en su calendario y en su detalle
    c = entrar("carlos@empresa.com")
    cal = c.get(f"/api/calendario?anio={date.today().year}").json()
    marca = next(x for x in cal["consultas"] if x["id"] == consulta["id"])
    assert marca["fecha"] == str(date.today()) and marca["hora_inicio"] == "10:00"
    det = c.get(f"/api/consultas/{consulta['id']}").json()
    assert det["sintomas"] == "Dolor de cabeza y mareo" and det["medicamentos"][0]["dosis"] == "500 mg"
    assert c.get("/api/consultas").json()[0]["detalle_clinico"] is True

    # El jefe solo ve que hubo consulta, sin información clínica
    laura = entrar("laura@empresa.com")
    lista = laura.get(f"/api/consultas?usuario_id={carlos['id']}").json()
    assert lista and lista[0]["detalle_clinico"] is False and "sintomas" not in lista[0]
    assert laura.get(f"/api/consultas/{consulta['id']}").status_code == 404
    cal_jefe = laura.get(f"/api/calendario?anio={date.today().year}&usuario_id={carlos['id']}").json()
    assert all(x["id"] is None for x in cal_jefe["consultas"])

    # Otro empleado no ve nada; nadie más que el médico puede registrar
    ana = entrar("ana@empresa.com")
    assert ana.get(f"/api/consultas/{consulta['id']}").status_code == 404
    assert ana.post("/api/consultas", json={"paciente_id": carlos["id"], "fecha": str(date.today()),
                                            "hora_inicio": "09:00", "sintomas": "x" * 5}).status_code == 403
    # El administrador sí ve los registros completos (y queda en auditoría)
    admin = entrar("admin@empresa.com", "Admin123")
    assert admin.get(f"/api/consultas/{consulta['id']}").json()["sintomas"] == "Dolor de cabeza y mareo"
    assert any(x["id"] == consulta["id"] for x in admin.get("/api/consultas?todos=true").json())
    from app.database import SessionLocal
    from app.models import Auditoria
    with SessionLocal() as db:
        assert db.query(Auditoria).filter(Auditoria.evento == "consulta_vista_admin").count() >= 1

    # Edición por el médico
    r = medico.put(f"/api/consultas/{consulta['id']}", json={**{k: consulta[k] for k in (
        "paciente_id", "fecha", "hora_inicio", "hora_fin", "sintomas", "diagnostico", "indicaciones")},
        "resultado": "envia_casa", "medicamentos": []})
    assert r.status_code == 200 and r.json()["resultado"] == "envia_casa" and r.json()["medicamentos"] == []


def test_validaciones_y_permiso_de_consulta_ya_no_se_solicita():
    medico = entrar("medico@empresa.com")
    pac = medico.get("/api/consultas/pacientes?rol=oficina").json()[0]
    futuro = str(date.today() + timedelta(days=2))
    r = medico.post("/api/consultas", json={"paciente_id": pac["id"], "fecha": futuro, "hora_inicio": "09:00", "sintomas": "Tos seca"})
    assert r.status_code == 422 and "futura" in r.text
    r = medico.post("/api/consultas", json={"paciente_id": pac["id"], "fecha": str(date.today()),
                                            "hora_inicio": "11:00", "hora_fin": "10:00", "sintomas": "Tos seca"})
    assert r.status_code == 422
    yo = medico.get("/api/auth/me").json()
    r = medico.post("/api/consultas", json={"paciente_id": yo["id"], "fecha": str(date.today()), "hora_inicio": "09:00", "sintomas": "Tos seca"})
    assert r.status_code == 422
    carlos = entrar("carlos@empresa.com")
    r = carlos.post("/api/permisos", json={"tipo": "consulta_medica", "fecha": str(date.today()),
                                           "hora_inicio": "09:00", "hora_fin": "10:00", "enviar": False})
    assert r.status_code == 422 and "médico de planta" in r.text


def test_buscador_de_pacientes():
    medico = entrar("medico@empresa.com")
    nombres = lambda q: [p["nombre"] for p in medico.get("/api/consultas/pacientes", params={"q": q}).json()]  # noqa: E731
    assert "Carlos Pérez" in nombres("perez carlos")       # sin acentos y en cualquier orden
    assert "Carlos Pérez" in nombres("CARLOS")
    assert nombres("Dra. Patricia") == []                    # el médico no aparece (no se atiende a sí mismo)
    carlos = next(p for p in medico.get("/api/consultas/pacientes", params={"q": "carlos"}).json() if p["nombre"] == "Carlos Pérez")
    assert medico.get("/api/consultas/pacientes", params={"q": carlos["numero_empleado"]}).json()[0]["id"] == carlos["id"]
    assert medico.get("/api/consultas/pacientes", params={"q": "zzz-no-existe"}).json() == []
