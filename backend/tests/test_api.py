from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.seed import main as seed

seed()
client = TestClient(app)
FIRMA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def login(email, pwd):
    """Cliente con su propia cookie de sesión y el encabezado CSRF, como el navegador."""
    c = TestClient(app)
    r = c.post("/api/auth/login-json", json={"email": email, "password": pwd})
    assert r.status_code == 200, r.text
    assert "sip_session" in c.cookies and "access_token" not in r.text
    c.headers["X-CSRF-Token"] = c.cookies["sip_csrf"]
    return c


def proximo_lunes(semanas=2):
    d = date.today() + timedelta(weeks=semanas)
    return d - timedelta(days=d.weekday())


def test_flujo_vacaciones_oficina():
    admin = login("admin@empresa.com", "Admin123")
    ana = login("ana@empresa.com", "Cambiar123")

    periodos = ana.get("/api/periodos").json()
    assert periodos and periodos[0]["horas_por_dia"] == 8
    p = periodos[0]
    lunes = proximo_lunes()

    # 5 días sueltos: permitidos porque el saldo (16) todavía alcanza para el bloque de 6, con aviso
    r = ana.post("/api/vacaciones/calcular", json={
        "periodo_id": p["id"], "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=4))}).json()
    assert not r["errores"] and r["advertencias"]
    assert not p["bloque_cumplido"]

    calc = ana.post("/api/vacaciones/calcular", json={
        "periodo_id": p["id"], "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7))}).json()
    assert not calc["errores"], calc
    r = ana.post("/api/vacaciones", json={
        "periodo_id": p["id"], "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)), "enviar": True, "firma": FIRMA})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert admin.get("/api/pendientes").json()["vacaciones"] >= 1
    assert admin.post(f"/api/vacaciones/{sid}/validar").json()["estado"] == "validado"
    saldo = ana.get("/api/periodos").json()[0]
    assert saldo["horas_validado"] == calc["horas"] and saldo["bloque_cumplido"]


def test_planta_dias_de_12_horas():
    carlos = login("carlos@empresa.com", "Cambiar123")
    p = carlos.get("/api/periodos").json()
    assert p[0]["horas_por_dia"] == 12
    # 2 años: periodo 1 -> 12 días ley -> 96 h -> 8 días de planta
    primero = min(p, key=lambda x: x["numero"])
    assert primero["dias_total"] == 8


def test_permiso_salida_intermedia_y_admin():
    admin = login("admin@empresa.com", "Admin123")
    maria = login("maria@empresa.com", "Cambiar123")
    r = maria.post("/api/permisos", json={
        "tipo": "salida_intermedia", "fecha": str(date.today()), "hora_inicio": "09:00", "hora_fin": "10:30",
        "motivo": "Trámite personal", "tipo_nomina": "con_goce", "firma": FIRMA, "enviar": True})
    assert r.status_code == 201, r.text
    assert r.json()["horas"] == 1.5
    r = admin.post(f"/api/permisos/{r.json()['id']}/validar", json={"observaciones": "Reposo"})
    assert r.json()["estado"] == "validado"
    res = maria.get("/api/resumen/permisos").json()
    assert res["por_tipo"]["salida_intermedia"]["validado"] == 1.5
    # Solo admin gestiona grupos
    assert maria.post("/api/grupos", json={"nombre": "X", "tipo_ciclo": "semanal"}).status_code == 403


def test_jefe_aprueba_y_ve_su_equipo():
    laura = login("laura@empresa.com", "Cambiar123")
    carlos = login("carlos@empresa.com", "Cambiar123")
    ana = login("ana@empresa.com", "Cambiar123")
    yo = carlos.get("/api/auth/me").json()
    jefes = carlos.get("/api/jefes").json()
    assert yo["jefe_nombre"] == "Laura Martínez" and any(j["id"] == yo["jefe_id"] for j in jefes)

    # Busca 4 días laborales seguidos dentro del ciclo 4x4 de Carlos
    periodo = carlos.get("/api/periodos").json()[0]
    inicio = date.today() + timedelta(days=20)
    for _ in range(40):
        calc = carlos.post("/api/vacaciones/calcular", json={
            "periodo_id": periodo["id"], "fecha_inicio": str(inicio), "fecha_fin": str(inicio + timedelta(days=3))}).json()
        if not calc["errores"] and calc["dias_habiles"] == 4:  # 4 días laborales seguidos del ciclo 4x4
            break
        inicio += timedelta(days=1)
    assert not calc["errores"] and calc["dias_habiles"] == 4, calc
    r = carlos.post("/api/vacaciones", json={
        "periodo_id": periodo["id"], "fecha_inicio": str(inicio), "fecha_fin": str(inicio + timedelta(days=3)),
        "enviar": True})
    assert r.status_code == 422 and "Firma" in r.text  # sin firma no se puede enviar
    r = carlos.post("/api/vacaciones", json={
        "periodo_id": periodo["id"], "fecha_inicio": str(inicio), "fecha_fin": str(inicio + timedelta(days=3)),
        "enviar": True, "firma": FIRMA})
    assert r.status_code == 201, r.text
    sol = r.json()
    assert sol["tiene_firma"]
    assert laura.get(f"/api/vacaciones/{sol['id']}/firma").json()["firma"] == FIRMA
    assert sol["aprobador_nombre"] == "Laura Martínez"

    assert laura.get("/api/pendientes").json()["vacaciones"] == 1
    assert [s["id"] for s in laura.get("/api/vacaciones?por_aprobar=true").json()] == [sol["id"]]
    # Ni el solicitante ni otro empleado pueden aprobar
    assert carlos.post(f"/api/vacaciones/{sol['id']}/validar").status_code == 403
    assert ana.post(f"/api/vacaciones/{sol['id']}/validar").status_code == 404
    assert laura.post(f"/api/vacaciones/{sol['id']}/validar").json()["estado"] == "validado"

    equipo = laura.get("/api/equipo").json()
    fila = next(m for m in equipo if m["usuario"]["id"] == yo["id"])
    assert fila["dias_tomados"] == 4
    # La jefa puede ver el detalle de su personal; otro empleado no
    assert laura.get(f"/api/periodos?usuario_id={yo['id']}").status_code == 200
    assert ana.get(f"/api/periodos?usuario_id={yo['id']}").status_code == 403


def test_asignar_grupo_solo_planta():
    admin = login("admin@empresa.com", "Admin123")
    usuarios = admin.get("/api/usuarios").json()
    ana = next(u for u in usuarios if u["email"] == "ana@empresa.com")
    grupo = admin.get("/api/grupos").json()[0]
    r = admin.put(f"/api/grupos/{grupo['id']}/miembros", json={"usuario_ids": [ana["id"]]})
    assert r.status_code == 400
    cal = admin.get(f"/api/calendario/equipo?anio={date.today().year}&mes=1")
    assert cal.status_code == 200 and cal.json()["empleados"]


def test_periodo_vencido_pierde_dias():
    maria = login("maria@empresa.com", "Cambiar123")  # 6 años: tiene periodos vencidos
    periodos = maria.get("/api/periodos").json()
    vencidos = [p for p in periodos if not p["vigente"]]
    assert vencidos and all(p["dias_disponible"] == 0 for p in vencidos)
    assert any(p["dias_perdidos"] > 0 for p in vencidos)
    # No se puede pedir sobre un periodo vencido
    v = vencidos[0]
    r = maria.post("/api/vacaciones/calcular", json={
        "periodo_id": v["id"], "fecha_inicio": str(date.today() + timedelta(days=10)),
        "fecha_fin": str(date.today() + timedelta(days=20))})
    assert any("vence" in e for e in r.json()["errores"])
    # El jefe ve los días perdidos de su colaboradora
    laura = login("laura@empresa.com", "Cambiar123")
    fila = next(m for m in laura.get("/api/equipo").json() if m["usuario"]["email_personal"] == "maria@empresa.com")
    assert fila["dias_perdidos"] > 0


def test_dias_laborales_sin_periodo_excluye_fines_y_festivos():
    ana = login("ana@empresa.com", "Cambiar123")
    # Viernes 13 a martes 17 de noviembre de 2026: sábado 14, domingo 15 y lunes 16 (Revolución) no cuentan
    r = ana.post("/api/vacaciones/dias-laborales", json={"fecha_inicio": "2026-11-13", "fecha_fin": "2026-11-17"}).json()
    assert r["dias_habiles"] == 2 and r["horas"] == 16 and r["fechas"] == ["2026-11-13", "2026-11-17"]
    motivos = {e["fecha"]: e["motivo"] for e in r["excluidos"]}
    assert motivos["2026-11-14"] == "Fin de semana" and motivos["2026-11-16"].startswith("Festivo")
    # Planta (ciclo 4x4): los días de descanso del ciclo no cuentan y se reportan como descanso
    carlos = login("carlos@empresa.com", "Cambiar123")
    r = carlos.post("/api/vacaciones/dias-laborales", json={"fecha_inicio": "2026-11-01", "fecha_fin": "2026-11-08"}).json()
    assert r["horas_por_dia"] == 12 and r["dias_habiles"] + len(r["excluidos"]) == 8
    assert ana.post("/api/vacaciones/dias-laborales", json={"fecha_inicio": "2026-11-17", "fecha_fin": "2026-11-13"}).status_code == 422
