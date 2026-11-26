"""App de Caseta: QR del empleado, entradas y salidas validadas contra permisos, equipos por código de barras y avisos."""
from datetime import timedelta

from app.database import SessionLocal
from app.models import VALIDADO, MovimientoCaseta, Permiso, Usuario
from app.routers.caseta_registro import codigo_qr
from app.sedes import ahora_en
from tests.test_caseta import _caseta
from tests.test_consultas import entrar


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
