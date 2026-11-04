"""Cadenas de aprobación personalizadas por tipo de permiso (jefe, jefe del jefe, GH, TI o una persona específica)."""
from datetime import date, datetime, timedelta

import pytest

from app import correo, flujos
from app.database import SessionLocal
from app.models import FlujoAprobacion, Permiso, TipoPermisoSede
from app.seed import main as seed
from tests.test_api import FIRMA, login
from tests.test_equipos import _ti
from tests.test_sharepoint import graph  # noqa: F401 (fixture)
from tests.test_aprobacion_flujo import entorno  # noqa: F401 (fixture del flujo HTTP)

seed()


@pytest.fixture
def cadena(monkeypatch):
    """Tipo de permiso de prueba por días (sin nómina) y limpieza de lo creado."""
    monkeypatch.setattr(flujos, "SEGUNDO_PLANO", False)  # avisos por correo en el mismo hilo
    adm = login("admin@empresa.com", "Admin123")
    r = adm.post("/api/tipos-permiso", json={"nombre": "Trámite con cadena", "modalidad": "dias", "pide_nomina": False})
    assert r.status_code == 201, r.text
    e = {"adm": adm, "tipo": r.json(), "flujos": []}
    yield e
    # Uno por uno, para que el ORM borre también los pasos (SQLite de pruebas no aplica las llaves foráneas)
    with SessionLocal() as db:
        for p in db.query(Permiso).filter(Permiso.tipo == e["tipo"]["clave"]):
            db.delete(p)
        db.flush()
        db.query(TipoPermisoSede).filter(TipoPermisoSede.id == e["tipo"]["id"]).delete()
        for f in db.query(FlujoAprobacion).filter(FlujoAprobacion.id.in_(e["flujos"])):
            db.delete(f)
        db.commit()


def _flujo(e, nombre, pasos):
    r = e["adm"].post("/api/flujos", json={"nombre": nombre, "pasos": pasos})
    assert r.status_code == 201, r.text
    e["flujos"].append(r.json()["id"])
    t = e["tipo"]
    r = e["adm"].put(f"/api/tipos-permiso/{t['id']}", json={"nombre": t["nombre"], "modalidad": "dias", "pide_nomina": False,
                                                            "flujo_id": r.json()["id"]})
    assert r.status_code == 200 and r.json()["flujo_nombre"] == nombre, r.text
    return r.json()


def _pedir(cliente, e, dia: date, esperado=201):
    # Una semana: con cualquier turno o ciclo (p. ej. planta 4×4) incluye días laborales
    r = cliente.post("/api/permisos", json={"tipo": e["tipo"]["clave"], "fecha": str(dia), "fecha_fin": str(dia + timedelta(days=6)),
                                            "motivo": "Trámite", "firma": FIRMA, "enviar": True})
    assert r.status_code == esperado, r.text
    return r.json()


def _mios(cliente, pid, estado="solicitado"):
    lista = cliente.get("/api/permisos", params={"por_aprobar": True, "estado": estado}).json()
    return any(p["id"] == pid for p in lista)


def test_cadena_jefe_ti_gh(cadena):
    adm, maria, laura, ti = cadena["adm"], login("maria@empresa.com", "Cambiar123"), \
        login("laura@empresa.com", "Cambiar123"), _ti()
    _flujo(cadena, "Jefe → TI → GH", [{"aprobador": "jefe"}, {"aprobador": "ti"}, {"aprobador": "gh"}])
    p = _pedir(maria, cadena, date(2031, 3, 3))
    assert [x["estado"] for x in p["pasos"]] == ["pendiente", "en_espera", "en_espera"]
    assert p["paso_actual"] == "Jefe directo" and p["pasos"][0]["aprobador_nombre"] == "Laura Martínez"

    # Paso 1: solo la jefa; TI todavía no puede
    assert _mios(laura, p["id"]) and not _mios(ti, p["id"])
    assert ti.post(f"/api/permisos/{p['id']}/validar").status_code in (403, 404)  # aún no le toca: ni la ve
    r = laura.post(f"/api/permisos/{p['id']}/validar").json()
    assert r["estado"] == "solicitado" and r["paso_actual"] == "TI"
    assert not _mios(laura, p["id"]) and _mios(laura, p["id"], estado=None)  # ya no es pendiente, sí historial
    assert ti.get("/api/pendientes").json()["permisos"] >= 1

    # Paso 2: TI (cualquiera con permiso de TI); la jefa ya no puede
    assert laura.post(f"/api/permisos/{p['id']}/validar").status_code == 403
    r = ti.post(f"/api/permisos/{p['id']}/validar").json()
    assert r["paso_actual"] == "GH de la sede"

    # Paso 3: GH valida y queda autorizado
    r = adm.post(f"/api/permisos/{p['id']}/validar").json()
    assert r["estado"] == "validado" and r["paso_actual"] is None
    assert [x["estado"] for x in r["pasos"]] == ["aprobado", "aprobado", "aprobado"]
    assert [x["decidido_por_nombre"] for x in r["pasos"]] == ["Laura Martínez", "Analista TI", "Administrador RH"]
    assert maria.get(f"/api/permisos/{p['id']}").json()["pasos"][1]["canal"] == "sip"


def test_rechazo_en_paso_intermedio_termina_la_solicitud(cadena):
    maria, laura, ana = login("maria@empresa.com", "Cambiar123"), login("laura@empresa.com", "Cambiar123"), \
        login("ana@empresa.com", "Cambiar123")
    ana_id = ana.get("/api/auth/me").json()["id"]
    _flujo(cadena, "Jefe → Ana → GH", [{"aprobador": "jefe"}, {"aprobador": "usuario", "usuario_id": ana_id},
                                        {"aprobador": "gh"}])
    p = _pedir(maria, cadena, date(2031, 3, 17))
    assert p["pasos"][1]["etiqueta"] == "Ana López", p["pasos"]
    laura.post(f"/api/permisos/{p['id']}/validar")
    assert _mios(ana, p["id"])
    r = ana.post(f"/api/permisos/{p['id']}/rechazar", json={"motivo": "No aplica este mes"}).json()
    assert r["estado"] == "rechazado" and r["motivo_rechazo"] == "No aplica este mes"
    assert [x["estado"] for x in r["pasos"]] == ["aprobado", "rechazado", "en_espera"]
    assert r["pasos"][1]["comentario"] == "No aplica este mes"


def test_gh_resuelve_directamente_y_la_misma_persona_aprueba_pasos_seguidos(cadena):
    adm, maria, ana = cadena["adm"], login("maria@empresa.com", "Cambiar123"), login("ana@empresa.com", "Cambiar123")
    _flujo(cadena, "Jefe → TI", [{"aprobador": "jefe"}, {"aprobador": "ti"}])
    p = _pedir(maria, cadena, date(2031, 3, 31))
    r = adm.post(f"/api/permisos/{p['id']}/validar").json()  # GH no es la jefa, pero puede validar directamente
    assert r["estado"] == "validado" and [x["estado"] for x in r["pasos"]] == ["aprobado", "omitido"]
    assert r["pasos"][0]["comentario"] == "Validado directamente por GH."

    # El jefe de Ana es el administrador, que también es GH: aprueba los dos pasos de una vez
    _flujo(cadena, "Jefe → GH", [{"aprobador": "jefe"}, {"aprobador": "gh"}])
    p = _pedir(ana, cadena, date(2031, 4, 14))
    r = adm.post(f"/api/permisos/{p['id']}/validar").json()
    assert r["estado"] == "validado" and [x["estado"] for x in r["pasos"]] == ["aprobado", "aprobado"]
    assert "misma persona" in r["pasos"][1]["comentario"]


def test_paso_sin_aprobador_se_omite_o_bloquea(cadena):
    adm, ana = cadena["adm"], login("ana@empresa.com", "Cambiar123")
    # El jefe de Ana (administrador) no tiene jefe: el paso "jefe del jefe" no tiene a quién pedírselo
    _flujo(cadena, "Jefe del jefe estricto", [{"aprobador": "jefe_del_jefe", "si_falta": "bloquear"}])
    r = ana.post("/api/permisos", json={"tipo": cadena["tipo"]["clave"], "fecha": "2031-05-12", "fecha_fin": "2031-05-18",
                                        "motivo": "Trámite", "firma": FIRMA, "enviar": True})
    assert r.status_code == 422 and "Jefe del jefe" in r.json()["detail"]
    _flujo(cadena, "Jefe del jefe o GH", [{"aprobador": "jefe_del_jefe"}, {"aprobador": "gh"}])
    p = _pedir(ana, cadena, date(2031, 4, 28))
    assert [x["estado"] for x in p["pasos"]] == ["omitido", "pendiente"] and p["paso_actual"] == "GH de la sede"
    assert adm.post(f"/api/permisos/{p['id']}/validar").json()["estado"] == "validado"


def test_solo_gh_configura_flujos_y_no_se_borra_uno_en_uso(cadena):
    adm, maria = cadena["adm"], login("maria@empresa.com", "Cambiar123")
    assert maria.post("/api/flujos", json={"nombre": "Mío", "pasos": [{"aprobador": "jefe"}]}).status_code == 403
    assert adm.post("/api/flujos", json={"nombre": "Vacío", "pasos": []}).status_code == 422
    assert adm.post("/api/flujos", json={"nombre": "Sin persona", "pasos": [{"aprobador": "usuario"}]}).status_code == 422
    t = _flujo(cadena, "En uso", [{"aprobador": "jefe"}])
    r = adm.delete(f"/api/flujos/{t['flujo_id']}")
    assert r.status_code == 400 and "Trámite con cadena" in r.json()["detail"]
    lista = adm.get("/api/flujos").json()
    assert any(f["nombre"] == "En uso" and f["tipos"] == ["Trámite con cadena"] for f in lista)
    b = adm.get("/api/bitacora", params={"seccion": "configuracion", "entidad": "Flujo de aprobación"}).json()["items"]
    assert any("En uso" in (x.get("resumen") or "") or x.get("entidad") == "Flujo de aprobación" for x in b)


def test_cada_paso_se_aprueba_en_teams_por_lista_y_avisa_por_correo(cadena, graph, monkeypatch):  # noqa: F811
    from app import sharepoint
    from app.models import ConfiguracionApp
    from tests.test_equipos_teams import TEAMS
    from tests.test_sharepoint import URL, super_login
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda cfg, dest, asunto, h, t: enviados.append((dest, asunto)))
    with SessionLocal() as db:  # remitente para que se envíen los avisos
        db.merge(ConfiguracionApp(clave="CORREO_REMITENTE", valor="sip@o-tek.com", cifrado=False, actualizado=datetime.now()))
        db.commit()
    adm, maria, laura = cadena["adm"], login("maria@empresa.com", "Cambiar123"), login("laura@empresa.com", "Cambiar123")
    sup = super_login()
    cfg = sup.put("/api/sharepoint/permisos/conectar", json={"url": URL}).json()
    assert sup.put("/api/sharepoint/permisos", json={"activo": True, "mapeo": cfg["mapeo"], "valores": cfg["valores"],
                                                      **TEAMS}).status_code == 200
    try:
        _flujo(cadena, "Jefe → GH (Teams)", [{"aprobador": "jefe"}, {"aprobador": "gh"}])
        p = _pedir(maria, cadena, date(2031, 6, 2))
        jefa = laura.get("/api/auth/me").json()["email"]
        gh = adm.get("/api/auth/me").json()["email"]
        assert any(jefa in d and "Permiso por aprobar (Jefe directo)" in a for d, a in enviados)
        sharepoint.procesar_pendientes()
        item = next(k for k, v in graph["items"].items() if v["Title"] == f"PER-{p['id']}")
        assert graph["items"][item]["CorreoJefe"] == jefa  # la tarjeta va a quien aprueba el paso actual

        # Paso 1 en Teams: avanza a GH, se vacía la decisión y la tarjeta ahora es para GH
        graph["items"][item].update({"Decision": "Approve", "Respondio": jefa})
        assert sharepoint.revisar_decisiones() == 1
        r = adm.get(f"/api/permisos/{p['id']}").json()
        assert r["estado"] == "solicitado" and r["paso_actual"] == "GH de la sede" and r["pasos"][0]["canal"] == "teams"
        assert any(gh in d and "(GH de la sede)" in a for d, a in enviados)
        assert sharepoint.revisar_decisiones() == 0  # la decisión vieja no se aplica al paso de GH
        sharepoint.procesar_pendientes()
        assert graph["items"][item]["Decision"] is None and gh in graph["items"][item]["CorreoJefe"]

        # Paso 2 en Teams: GH aprueba y el permiso queda validado
        graph["items"][item].update({"Decision": "Approve", "Respondio": gh})
        assert sharepoint.revisar_decisiones() == 1
        r = adm.get(f"/api/permisos/{p['id']}").json()
        assert r["estado"] == "validado" and [x["canal"] for x in r["pasos"]] == ["teams", "teams"]
    finally:
        sup.delete("/api/sharepoint/permisos")
        with SessionLocal() as db:
            db.query(ConfiguracionApp).filter(ConfiguracionApp.clave == "CORREO_REMITENTE").delete()
            db.commit()


def test_cada_paso_se_aprueba_en_teams_por_flujo_http(cadena, entorno):  # noqa: F811
    from app import aprobacion_flujo as af
    from tests.test_aprobacion_flujo import FLUJO, LISTA
    from tests.test_sharepoint import super_login
    adm, maria, laura = cadena["adm"], login("maria@empresa.com", "Cambiar123"), login("laura@empresa.com", "Cambiar123")
    sup = super_login()
    assert sup.put("/api/aprobacion-flujo", json={"activo": True, "tipos": ["permisos"], "flujo_url": FLUJO,
                                                  "lista_url": LISTA, "cuenta_flujo": "Flujos@o-tek.com"}).status_code == 200
    try:
        _flujo(cadena, "Jefe → TI → GH (HTTP)", [{"aprobador": "jefe"}, {"aprobador": "ti", "teams": False},
                                                {"aprobador": "gh"}])
        ti = _ti()
        p = _pedir(maria, cadena, date(2031, 6, 16))
        af.enviar_pendientes()
        jefa = laura.get("/api/auth/me").json()["email"]
        t1 = entorno["enviados"][-1]
        assert t1["folio"] == f"PER-{p['id']}" and t1["correoJefe"] == jefa
        entorno["decisiones"].append({"Token": t1["token"], "Decision": "Approve", "Respondio": jefa})
        assert af.revisar_decisiones() == 1
        assert adm.get(f"/api/permisos/{p['id']}").json()["paso_actual"] == "TI"
        # El paso de TI no va a Teams: no se manda tarjeta y la decisión vieja no sirve
        antes = len(entorno["enviados"])
        af.enviar_pendientes()
        assert len(entorno["enviados"]) == antes and af.revisar_decisiones() == 0
        ti.post(f"/api/permisos/{p['id']}/validar")
        # El paso de GH sí: nueva tarjeta con otro token
        af.enviar_pendientes()
        t3 = entorno["enviados"][-1]
        gh = adm.get("/api/auth/me").json()["email"]
        assert t3["token"] != t1["token"] and gh in t3["correoJefe"]
        entorno["decisiones"].append({"Token": t1["token"], "Decision": "Approve", "Respondio": gh})  # token viejo
        assert af.revisar_decisiones() == 0
        entorno["decisiones"].append({"Token": t3["token"], "Decision": "Approve", "Respondio": gh})
        assert af.revisar_decisiones() == 1
        assert adm.get(f"/api/permisos/{p['id']}").json()["estado"] == "validado"
    finally:
        sup.put("/api/aprobacion-flujo", json={"activo": False})
