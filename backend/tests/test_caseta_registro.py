"""App de Caseta: QR del empleado, entradas y salidas validadas contra permisos, equipos por código de barras y avisos."""
from datetime import timedelta

from app.database import SessionLocal
from app.models import VALIDADO, MovimientoCaseta, Permiso, Usuario
from app.routers.caseta_registro import codigo_qr
from app.sedes import ahora_en
from tests.test_caseta import _caseta
from tests.test_consultas import entrar


import pytest


def _qr(activo):
    from app.models import Sede
    with SessionLocal() as db:
        for sd in db.query(Sede).all():
            sd.caseta_qr = activo
        db.commit()


@pytest.fixture(autouse=True)
def qr_activo():
    """Las pruebas de escaneo necesitan el QR activo en la sede (viene apagado por defecto)."""
    _qr(True)
    yield
    _qr(False)


def _usuario(email):
    with SessionLocal() as db:
        return db.query(Usuario).filter((Usuario.email == email) | (Usuario.email_personal == email)).one().id


def _permiso(uid, tipo, desde_min, hasta_min):
    """Permiso validado de hoy, con horario relativo a la hora local actual de la sede."""
    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        ahora = ahora_en(u.sede).replace(second=0, microsecond=0)
        ini, fin = ahora + timedelta(minutes=desde_min), ahora + timedelta(minutes=hasta_min)
        p = Permiso(usuario_id=uid, tipo=tipo, fecha=ahora.date(), hora_inicio=ini.time(), hora_fin=fin.time(),
                    horas=(hasta_min - desde_min) / 60, motivo="prueba caseta", estado=VALIDADO)
        db.add(p)
        db.commit()
        return p.id


def _limpiar(uid, *permisos):
    with SessionLocal() as db:
        db.query(MovimientoCaseta).filter(MovimientoCaseta.usuario_id == uid).delete()
        for pid in permisos:
            db.query(Permiso).filter(Permiso.id == pid).delete()
        db.commit()


def test_qr_del_empleado():
    carlos = entrar("carlos@empresa.com")
    mio = carlos.get("/api/caseta/qr/mio").json()
    assert mio["codigo"] == codigo_qr(_usuario("carlos@empresa.com")) and mio["codigo"].startswith("SIPO-E1.")
    # Solo GH ve el QR de otros
    assert carlos.get(f"/api/caseta/qr/{_usuario('laura@empresa.com')}").status_code == 403
    adm = entrar("admin@empresa.com", "Admin123")
    assert adm.get(f"/api/caseta/qr/{_usuario('carlos@empresa.com')}").json()["codigo"] == mio["codigo"]
    # Un QR alterado o ajeno no sirve
    cas = _caseta()
    falso = mio["codigo"][:-1] + ("0" if mio["codigo"][-1] != "0" else "1")
    assert cas.post("/api/caseta/escanear", json={"codigo": falso}).status_code == 422
    assert cas.post("/api/caseta/escanear", json={"codigo": "hola"}).status_code == 422
    assert carlos.post("/api/caseta/escanear", json={"codigo": mio["codigo"]}).status_code == 403


def test_salida_y_regreso_con_permiso_y_sin_permiso():
    cas = _caseta()
    uid = _usuario("carlos@empresa.com")
    otro = _usuario("laura@empresa.com")
    _limpiar(uid)
    _limpiar(otro)
    pid = _permiso(uid, "salida_intermedia", -5, 60)
    try:
        r = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid)})
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["tipo"] == "salida" and s["con_permiso"] and s["permiso"]["id"] == pid and "regresar" in s["mensaje"]
        # Doble escaneo seguido: el mismo registro
        again = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid)}).json()
        assert again["repetido"] and again["id"] == s["id"]
        # Regreso
        e = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid), "tipo": "entrada"}).json()
        assert e["tipo"] == "entrada" and e["con_permiso"] and "Regreso" in e["mensaje"]

        # Sin permiso: se guarda, pero no válido
        n = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(otro)}).json()
        assert n["tipo"] == "salida" and n["con_permiso"] is False and "No tiene" in n["mensaje"]

        movs = cas.get("/api/caseta/movimientos", params={"clase": "persona"}).json()
        assert {m["id"] for m in movs} >= {s["id"], e["id"], n["id"]}
    finally:
        _limpiar(uid, pid)
        _limpiar(otro)


def test_salida_antes_de_hora_y_llegada_tarde():
    cas = _caseta()
    uid = _usuario("carlos@empresa.com")
    _limpiar(uid)
    temprano = _permiso(uid, "salida_temprana", 120, 180)
    try:
        r = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid)}).json()
        assert r["tipo"] == "salida" and r["con_permiso"] is False and "todavía no es hora" in r["mensaje"]
    finally:
        _limpiar(uid, temprano)
    tarde = _permiso(uid, "llegada_tarde", -60, 5)
    try:
        r = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid)}).json()
        assert r["tipo"] == "entrada" and r["con_permiso"] and "Llegada tarde autorizada" in r["mensaje"]
    finally:
        _limpiar(uid, tarde)


def test_avisos_solo_por_horas_y_ordenados():
    cas = _caseta()
    uid = _usuario("carlos@empresa.com")
    salida = _permiso(uid, "salida_temprana", 30, 90)    # sale en 30 min
    llegada = _permiso(uid, "llegada_tarde", -60, 60)    # entra en 60 min
    try:
        av = cas.get("/api/caseta/avisos").json()["avisos"]
        mios = [a for a in av if a["id"] in (salida, llegada)]
        assert [a["id"] for a in mios] == [salida, llegada]  # por la hora del movimiento en la puerta
        assert all(a["es_hoy"] for a in mios) and mios[1]["hora"] == mios[1]["hora_fin"]
        assert not any(a["tipo"] == "home_office" for a in av)
        hoy = cas.get("/api/caseta/hoy").json()["por_horas"]
        orden = [f["id"] for f in hoy if f["id"] in (salida, llegada)]
        assert orden == [salida, llegada]
    finally:
        _limpiar(uid, salida, llegada)


def test_equipo_por_codigo_de_barras():
    cas = _caseta()
    uid = _usuario("carlos@empresa.com")
    cod = "INV-00123"
    with SessionLocal() as db:
        db.query(MovimientoCaseta).filter(MovimientoCaseta.equipo_codigo == cod).delete()
        db.commit()
    try:
        assert cas.get(f"/api/caseta/equipos/{cod}").json()["sugerido"] == "salida"
        s = cas.post("/api/caseta/equipos", json={"codigo": " inv-00123 ", "tipo": "salida", "usuario_id": uid}).json()
        assert s["equipo_codigo"] == cod and s["con_permiso"] is False and "NO tiene" in s["mensaje"]
        info = cas.get(f"/api/caseta/equipos/{cod}").json()
        assert info["sugerido"] == "entrada" and info["ultimo"]["persona"]["usuario_id"] == uid
        e = cas.post("/api/caseta/equipos", json={"codigo": cod, "tipo": "entrada"}).json()
        assert e["con_permiso"] and e["tipo"] == "entrada"
        assert cas.post("/api/caseta/equipos", json={"codigo": cod, "tipo": "otro"}).status_code == 422
    finally:
        _limpiar(uid)
        with SessionLocal() as db:
            db.query(MovimientoCaseta).filter(MovimientoCaseta.equipo_codigo == cod).delete()
            db.commit()


def _permiso_en(uid, tipo, dias, delta_min=0):
    """Permiso validado a `dias` de hoy, a la hora local actual + `delta_min` (una hora de duración)."""
    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        base = ahora_en(u.sede).replace(tzinfo=None, second=0, microsecond=0) + timedelta(days=dias, minutes=delta_min)
        fin = base + timedelta(hours=1)
        p = Permiso(usuario_id=uid, tipo=tipo, fecha=base.date(), hora_inicio=base.time(),
                    hora_fin=fin.time() if fin.date() == base.date() else base.time().replace(hour=23, minute=59),
                    horas=1, motivo="prueba caseta", estado=VALIDADO)
        db.add(p)
        db.commit()
        return p.id


def test_proximos_solo_hoy_y_48_horas():
    cas = _caseta()
    uid = _usuario("carlos@empresa.com")
    ayer = _permiso_en(uid, "salida_temprana", -1)
    manana = _permiso_en(uid, "salida_temprana", 1)
    dentro = _permiso_en(uid, "salida_temprana", 2, -30)   # pasado mañana, antes de cumplir 48 h
    fuera = _permiso_en(uid, "salida_temprana", 2, 30)     # pasado mañana, después de 48 h
    lejos = _permiso_en(uid, "salida_temprana", 4)
    try:
        dias = cas.get("/api/caseta/proximos").json()["dias"]
        ids = [p["id"] for d in dias for p in d["permisos"]]
        assert manana in ids and dentro in ids
        assert not {ayer, fuera, lejos} & set(ids)
        assert all(not p["por_dias"] for d in dias for p in d["permisos"])
        av = [a["id"] for a in cas.get("/api/caseta/avisos").json()["avisos"]]
        assert manana in av and dentro in av and not {ayer, fuera, lejos} & set(av)
    finally:
        _limpiar(uid, ayer, manana, dentro, fuera, lejos)


def test_usuarios_de_caseta_para_el_inicio():
    _caseta()
    from fastapi.testclient import TestClient
    from app.main import app
    lista = TestClient(app).get("/api/auth/usuarios-caseta").json()
    assert {"nombre": "Guardia Caseta", "usuario": "CAS-1"} in lista
    assert all(set(u) == {"nombre", "usuario"} for u in lista)  # sin correos ni otros datos


def test_retardo_con_hora_automatica(monkeypatch):
    from app import correo
    from app.routers import caseta as mod
    monkeypatch.setattr(correo, "enviar", lambda *a, **k: None)
    cas = _caseta()
    carlos = next(e for e in cas.get("/api/caseta/empleados", params={"q": "perez"}).json() if e["nombre"] == "Carlos Pérez")
    real = mod.ahora_en
    entrada = carlos["entrada_hoy"]
    h, m = map(int, entrada.split(":"))
    monkeypatch.setattr(mod, "ahora_en", lambda sede: real(sede).replace(hour=h, minute=m) + timedelta(minutes=20))
    r = cas.post("/api/caseta/retardos", json={"usuario_id": carlos["id"], "motivo": "Tráfico"})
    try:
        assert r.status_code == 201, r.text
        assert r.json()["hora_fin"] == (real(None).replace(hour=h, minute=m) + timedelta(minutes=20)).strftime("%H:%M")
    finally:
        with SessionLocal() as db:
            db.query(Permiso).filter(Permiso.id == r.json().get("id")).delete()
            db.commit()


def test_tolerancias_configurables_por_sede():
    from app.models import Sede
    adm = entrar("admin@empresa.com", "Admin123")
    pol = adm.get("/api/politica").json()
    assert pol["tol_salida_antes"] == 15 and pol["tol_llegada_despues"] == 15 and pol["tol_regreso_despues"] == 15
    cas = _caseta()
    uid = _usuario("carlos@empresa.com")
    salida = _permiso(uid, "salida_temprana", 10, 90)   # su salida es en 10 min
    try:
        # Con 5 min de tolerancia todavía no puede salir
        r = adm.put("/api/politica", json={**{k: pol[k] for k in ("meses_vigencia", "equivalencia_horas", "dias_anticipacion",
                                                                  "modulo_consultas", "modulo_cumpleanos", "generacion_dias",
                                                                  "aprobacion_gh_vacaciones", "aprobacion_gh_permisos")},
                                           "tol_salida_antes": 5})
        assert r.status_code == 200 and r.json()["tol_salida_antes"] == 5
        m = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid), "tipo": "salida"}).json()
        assert not m["con_permiso"] and "todavía no es hora" in m["mensaje"]
        # Con 15 min sí (un segundo escaneo como entrada intermedia no aplica: se limpia antes)
        _limpiar(uid)
        with SessionLocal() as db:
            db.get(Usuario, uid).sede.tol_salida_antes = 15
            db.commit()
        m = cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid), "tipo": "salida"}).json()
        assert m["con_permiso"]
        assert adm.put("/api/politica", json={"tol_salida_antes": 500}).status_code == 422
    finally:
        with SessionLocal() as db:
            for s in db.query(Sede).all():
                s.tol_salida_antes = s.tol_llegada_despues = s.tol_regreso_despues = 15
            db.commit()
        _limpiar(uid, salida)


def test_qr_desactivado_y_uso_del_permiso_con_un_clic():
    _qr(False)
    cas = _caseta()
    uid = _usuario("carlos@empresa.com")
    carlos = entrar("carlos@empresa.com")
    assert carlos.get("/api/caseta/qr/mio").json() == {"activo": False}
    assert cas.post("/api/caseta/escanear", json={"codigo": codigo_qr(uid)}).status_code == 422
    salida = _permiso(uid, "salida_intermedia", -5, 60)   # sale ahora y regresa en una hora
    tarde = _permiso(uid, "llegada_tarde", -60, 0)
    try:
        hoy = cas.get("/api/caseta/hoy").json()
        assert hoy["qr_activo"] is False
        fila = next(f for f in hoy["por_horas"] if f["id"] == salida)
        assert fila["uso"]["siguiente"] == "salida" and fila["uso"]["regreso"]
        r = cas.post(f"/api/caseta/permisos/{salida}/usar")
        assert r.status_code == 201, r.text
        assert r.json()["tipo"] == "salida" and r.json()["uso"]["siguiente"] == "entrada"
        # Deshacer un toque equivocado y volver a registrar
        assert cas.delete(f"/api/caseta/movimientos/{r.json()['id']}").status_code == 204
        cas.post(f"/api/caseta/permisos/{salida}/usar")
        e = cas.post(f"/api/caseta/permisos/{salida}/usar").json()
        assert e["tipo"] == "entrada" and e["uso"]["siguiente"] is None and "Regreso" in e["mensaje"]
        assert cas.post(f"/api/caseta/permisos/{salida}/usar").status_code == 409   # ya usado
        t = cas.post(f"/api/caseta/permisos/{tarde}/usar").json()
        assert t["tipo"] == "entrada" and t["con_permiso"]
        # Otro usuario de caseta no puede deshacer lo ajeno
        assert carlos.delete(f"/api/caseta/movimientos/{t['id']}").status_code == 403
    finally:
        _limpiar(uid, salida, tarde)


def test_caseta_solo_ve_nombre_corto_y_el_permiso():
    from app.vista_caseta import nombre_corto
    assert nombre_corto("Felipe De Jesus Reyes Reyes") == "Felipe Reyes"
    assert nombre_corto("Jose Antonio Lanuza Razo") == "Jose Lanuza"
    assert nombre_corto("Juan Carlos De la Cruz López") == "Juan De la Cruz"
    assert nombre_corto("Juan Pérez García") == "Juan Pérez"
    assert nombre_corto("Ana López") == "Ana López"
    uid = _usuario("carlos@empresa.com")
    with SessionLocal() as db:
        u = db.get(Usuario, uid)
        completo, numero = u.nombre, u.numero_empleado
        u.nombre = "Carlos Alberto Méndez Ruiz"
        db.commit()
    _limpiar(uid)
    pid = _permiso(uid, "salida_intermedia", -5, 60)
    try:
        cas = _caseta()
        hoy = cas.get("/api/caseta/hoy")
        assert hoy.status_code == 200
        fila = next(f for f in hoy.json()["por_horas"] if f["id"] == pid)
        assert fila["nombre"] == "Carlos Méndez"
        assert not {"numero_empleado", "puesto", "departamento"} & fila.keys()
        assert "Carlos Alberto" not in hoy.text and f'"{numero}"' not in hoy.text
        # Al registrar, el mensaje también lleva el nombre corto
        r = cas.post(f"/api/caseta/permisos/{pid}/usar")
        assert r.status_code == 201 and "Carlos Alberto" not in r.text and "numero_empleado" not in r.text
        assert "numero_empleado" not in cas.get("/api/caseta/movimientos").text
        # La búsqueda de caseta es solo por nombre
        assert cas.get("/api/caseta/empleados", params={"q": numero}).json() == [] or numero.isalpha()
        assert [e["id"] for e in cas.get("/api/caseta/empleados", params={"usuario_id": uid}).json()] == [uid]
        # GH sigue viendo todo
        adm = entrar("admin@empresa.com", "Admin123")
        f2 = next(f for f in adm.get("/api/caseta/hoy").json()["por_horas"] if f["id"] == pid)
        assert f2["nombre"] == "Carlos Alberto Méndez Ruiz" and f2["numero_empleado"] == numero
    finally:
        _limpiar(uid, pid)
        with SessionLocal() as db:
            db.get(Usuario, uid).nombre = completo
            db.commit()


def test_tarjetas_para_imprimir():
    carlos, laura = _usuario("carlos@empresa.com"), _usuario("laura@empresa.com")
    _qr(False)  # se pueden imprimir antes de activar el QR
    adm = entrar("admin@empresa.com", "Admin123")
    r = adm.post("/api/caseta/tarjetas", json={"ids": [carlos, laura]})
    assert r.status_code == 200, r.text
    t = {x["id"]: x for x in r.json()}
    assert t[carlos]["codigo"] == codigo_qr(carlos) and t[carlos]["qr_activo"] is False
    assert {"nombre", "numero_empleado", "puesto", "departamento", "tiene_foto"} <= t[laura].keys()
    assert entrar("carlos@empresa.com").post("/api/caseta/tarjetas", json={"ids": [carlos]}).status_code == 403
    assert adm.post("/api/caseta/tarjetas", json={"ids": []}).status_code == 422
