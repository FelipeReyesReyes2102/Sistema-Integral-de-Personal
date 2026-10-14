"""Política de vacaciones y permisos por sede, tipos de jornada y roles GH / Gerencia GH."""
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.seed import main as seed

seed()
HOY = date.today()
FIRMA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def entrar(usuario, pwd, sede=None):
    c = TestClient(app)
    r = c.post("/api/auth/login-json", json={"usuario": usuario, "password": pwd})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    if sede:
        c.headers["X-Sede-Id"] = str(sede)
    return c


def preparar():
    """Super administrador, sede Bogotá (creada por la API, con sus jornadas base) y su GH."""
    with SessionLocal() as db:
        if not db.query(Usuario).filter(Usuario.email == "super.pol@o-tek.com").first():
            db.add(Usuario(numero_empleado="SP-1", nombre="Super Política", email="super.pol@o-tek.com", rol="superadmin",
                           password_hash=hash_password("Clave12345"), fecha_ingreso=date(2020, 1, 1),
                           sede_id=sede_principal(db).id))
            db.commit()
    su = entrar("super.pol@o-tek.com", "Clave12345")
    sedes = {s["nombre"]: s["id"] for s in su.get("/api/sedes").json()}
    if "O-Tek Colombia - Bogotá" not in sedes:
        r = su.post("/api/sedes", json={"nombre": "O-Tek Colombia - Bogotá", "zona_horaria": "America/Bogota"})
        assert r.status_code == 201, r.text
        sedes["O-Tek Colombia - Bogotá"] = r.json()["id"]
    bog = sedes["O-Tek Colombia - Bogotá"]
    gh = {"numero_empleado": "BG-1", "nombre": "GH Bogotá", "email": "gh.bog@o-tek.com", "rol": "admin",
          "fecha_ingreso": "2021-02-01", "sede_id": bog, "password": "Clave12345"}
    if not any(u["numero_empleado"] == "BG-1" for u in su.get("/api/usuarios").json()):
        assert su.post("/api/usuarios", json=gh).status_code == 201
        with SessionLocal() as db:  # la contraseña indicada por el administrador también es temporal
            db.query(Usuario).filter(Usuario.numero_empleado == "BG-1").one().debe_cambiar_password = False
            db.commit()
    return su, bog


def test_politica_por_sede_y_jornadas():
    su, bog = preparar()
    gh = entrar("gh.bog@o-tek.com", "Clave12345")
    pol = gh.get("/api/politica").json()
    assert pol["sede_nombre"] == "O-Tek Colombia - Bogotá" and pol["meses_vigencia"] == 18
    assert [j["nombre"] for j in pol["jornadas"]] == ["Oficina", "Planta 12 h"]

    # Bogotá: 24 meses de vigencia, 5 días de anticipación, sin home office y días completos (no equivalencia)
    r = gh.put("/api/politica", json={"meses_vigencia": 24, "equivalencia_horas": False, "dias_anticipacion": 5,
                                      "tipos_permiso": ["llegada_tarde", "salida_temprana"], "home_office_max_dias": 10,
                                      "modulo_consultas": False, "modulo_cumpleanos": True})
    assert r.status_code == 200 and r.json()["tipos_permiso"] == ["llegada_tarde", "salida_temprana"]
    # Jornada propia de la sede: turnos de 10 h con bloque mínimo de 5 días
    r = gh.post("/api/jornadas", json={"nombre": "Planta 10 h", "horas_dia": 10, "bloque_minimo": 5, "usa_ciclo_grupo": False})
    assert r.status_code == 201
    jid = r.json()["id"]
    # Tabla: 15 días por año
    gh.put("/api/reglas-antiguedad", json=[{"anios_desde": 1, "anios_hasta": 50, "dias": 15}])

    emp = {"numero_empleado": "BG-2", "nombre": "Operario Bogotá", "email": "op.bog@o-tek.com", "rol": "oficina",
           "fecha_ingreso": (HOY - relativedelta(years=1, months=2)).isoformat(), "tipo_jornada_id": jid,
           "password": "Clave12345"}
    r = gh.post("/api/usuarios", json=emp)
    assert r.status_code == 201, r.text
    assert r.json()["tipo_jornada_nombre"] == "Planta 10 h" and r.json()["sede_id"] == bog
    with SessionLocal() as db:
        db.query(Usuario).filter(Usuario.numero_empleado == "BG-2").one().debe_cambiar_password = False
        db.commit()
    op = entrar("op.bog@o-tek.com", "Clave12345")
    p = op.get("/api/periodos").json()[0]
    # Días completos: 15 días de 10 h; vence a los 24 meses
    assert p["dias_ley"] == 15 and p["horas_por_dia"] == 10 and p["dias_total"] == 15 and p["minimo_dias"] == 5
    assert p["fecha_vencimiento"] == (date.fromisoformat(p["fecha_inicio"]) + relativedelta(months=24) - timedelta(days=1)).isoformat()

    # Permisos deshabilitados y anticipación mínima
    ho = {"tipo": "home_office", "fecha": (HOY + timedelta(days=10)).isoformat(),
          "fecha_fin": (HOY + timedelta(days=11)).isoformat(), "motivo": "x", "aprobador_id": None}
    r = op.post("/api/permisos", json=ho)
    assert r.status_code == 422 and "no está habilitado" in r.json()["detail"]
    lunes = HOY + timedelta(days=(7 - HOY.weekday()) % 7 or 7)
    c = op.post("/api/vacaciones/calcular", json={"periodo_id": p["id"], "fecha_inicio": HOY.isoformat() if HOY.weekday() < 5 else lunes.isoformat(),
                                                   "fecha_fin": (lunes + timedelta(days=4)).isoformat()}).json()
    if (lunes - HOY).days < 5 or HOY.weekday() < 5:
        assert any("anticipación" in e for e in c["errores"])

    # México no cambia
    ana = entrar("ana@empresa.com", "Cambiar123")
    pa = ana.get("/api/periodos").json()[0]
    assert pa["fecha_vencimiento"] == (date.fromisoformat(pa["fecha_inicio"]) + relativedelta(months=18) - timedelta(days=1)).isoformat()
    assert pa["horas_por_dia"] == 8
    assert ana.get("/api/politica").json()["tipos_permiso"][-1] == "home_office"

    # Un GH de otra sede no modifica la política de Bogotá (el selector se ignora)
    mx = entrar("admin@empresa.com", "Admin123", sede=bog)
    assert mx.get("/api/politica").json()["sede_nombre"] == "O-tek México"
    # No se borra una jornada en uso
    assert gh.delete(f"/api/jornadas/{jid}").status_code == 400
