"""Cadenas de aprobación personalizadas por tipo de permiso (jefe, jefe del jefe, GH, TI o una persona específica)."""
from datetime import date, timedelta

import pytest

from app.database import SessionLocal
from app.models import FlujoAprobacion, Permiso, TipoPermisoSede
from app.seed import main as seed
from tests.test_api import FIRMA, login
from tests.test_equipos import _ti
from tests.test_sharepoint import graph  # noqa: F401 (fixture)

seed()


@pytest.fixture
def entorno():
    """Tipo de permiso de prueba por días (sin nómina) y limpieza de lo creado."""
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


def test_cadena_jefe_ti_gh(entorno):
    adm, maria, laura, ti = entorno["adm"], login("maria@empresa.com", "Cambiar123"), \
        login("laura@empresa.com", "Cambiar123"), _ti()
    _flujo(entorno, "Jefe → TI → GH", [{"aprobador": "jefe"}, {"aprobador": "ti"}, {"aprobador": "gh"}])
    p = _pedir(maria, entorno, date(2031, 3, 3))
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


def test_rechazo_en_paso_intermedio_termina_la_solicitud(entorno):
    maria, laura, ana = login("maria@empresa.com", "Cambiar123"), login("laura@empresa.com", "Cambiar123"), \
        login("ana@empresa.com", "Cambiar123")
    ana_id = ana.get("/api/auth/me").json()["id"]
    _flujo(entorno, "Jefe → Ana → GH", [{"aprobador": "jefe"}, {"aprobador": "usuario", "usuario_id": ana_id},
                                        {"aprobador": "gh"}])
    p = _pedir(maria, entorno, date(2031, 3, 17))
    assert p["pasos"][1]["etiqueta"] == "Ana López", p["pasos"]
    laura.post(f"/api/permisos/{p['id']}/validar")
    assert _mios(ana, p["id"])
    r = ana.post(f"/api/permisos/{p['id']}/rechazar", json={"motivo": "No aplica este mes"}).json()
    assert r["estado"] == "rechazado" and r["motivo_rechazo"] == "No aplica este mes"
    assert [x["estado"] for x in r["pasos"]] == ["aprobado", "rechazado", "en_espera"]
    assert r["pasos"][1]["comentario"] == "No aplica este mes"


def test_gh_resuelve_directamente_y_la_misma_persona_aprueba_pasos_seguidos(entorno):
    adm, maria, ana = entorno["adm"], login("maria@empresa.com", "Cambiar123"), login("ana@empresa.com", "Cambiar123")
    _flujo(entorno, "Jefe → TI", [{"aprobador": "jefe"}, {"aprobador": "ti"}])
    p = _pedir(maria, entorno, date(2031, 3, 31))
    r = adm.post(f"/api/permisos/{p['id']}/validar").json()  # GH no es la jefa, pero puede validar directamente
    assert r["estado"] == "validado" and [x["estado"] for x in r["pasos"]] == ["aprobado", "omitido"]
    assert r["pasos"][0]["comentario"] == "Validado directamente por GH."

    # El jefe de Ana es el administrador, que también es GH: aprueba los dos pasos de una vez
    _flujo(entorno, "Jefe → GH", [{"aprobador": "jefe"}, {"aprobador": "gh"}])
    p = _pedir(ana, entorno, date(2031, 4, 14))
    r = adm.post(f"/api/permisos/{p['id']}/validar").json()
    assert r["estado"] == "validado" and [x["estado"] for x in r["pasos"]] == ["aprobado", "aprobado"]
    assert "misma persona" in r["pasos"][1]["comentario"]


def test_paso_sin_aprobador_se_omite_o_bloquea(entorno):
    adm, ana = entorno["adm"], login("ana@empresa.com", "Cambiar123")
    # El jefe de Ana (administrador) no tiene jefe: el paso "jefe del jefe" no tiene a quién pedírselo
    _flujo(entorno, "Jefe del jefe estricto", [{"aprobador": "jefe_del_jefe", "si_falta": "bloquear"}])
    r = ana.post("/api/permisos", json={"tipo": entorno["tipo"]["clave"], "fecha": "2031-05-12", "fecha_fin": "2031-05-18",
                                        "motivo": "Trámite", "firma": FIRMA, "enviar": True})
    assert r.status_code == 422 and "Jefe del jefe" in r.json()["detail"]
    _flujo(entorno, "Jefe del jefe o GH", [{"aprobador": "jefe_del_jefe"}, {"aprobador": "gh"}])
    p = _pedir(ana, entorno, date(2031, 4, 28))
    assert [x["estado"] for x in p["pasos"]] == ["omitido", "pendiente"] and p["paso_actual"] == "GH de la sede"
    assert adm.post(f"/api/permisos/{p['id']}/validar").json()["estado"] == "validado"


def test_solo_gh_configura_flujos_y_no_se_borra_uno_en_uso(entorno):
    adm, maria = entorno["adm"], login("maria@empresa.com", "Cambiar123")
    assert maria.post("/api/flujos", json={"nombre": "Mío", "pasos": [{"aprobador": "jefe"}]}).status_code == 403
    assert adm.post("/api/flujos", json={"nombre": "Vacío", "pasos": []}).status_code == 422
    assert adm.post("/api/flujos", json={"nombre": "Sin persona", "pasos": [{"aprobador": "usuario"}]}).status_code == 422
    t = _flujo(entorno, "En uso", [{"aprobador": "jefe"}])
    r = adm.delete(f"/api/flujos/{t['flujo_id']}")
    assert r.status_code == 400 and "Trámite con cadena" in r.json()["detail"]
    lista = adm.get("/api/flujos").json()
    assert any(f["nombre"] == "En uso" and f["tipos"] == ["Trámite con cadena"] for f in lista)
    b = adm.get("/api/bitacora", params={"seccion": "configuracion", "entidad": "Flujo de aprobación"}).json()["items"]
    assert any("En uso" in (x.get("resumen") or "") or x.get("entidad") == "Flujo de aprobación" for x in b)


def test_teams_resuelve_solo_el_primer_paso(entorno, graph):  # noqa: F811
    from app import sharepoint
    from tests.test_equipos_teams import TEAMS
    from tests.test_sharepoint import URL, super_login
    adm, maria, laura = entorno["adm"], login("maria@empresa.com", "Cambiar123"), login("laura@empresa.com", "Cambiar123")
    sup = super_login()
    cfg = sup.put("/api/sharepoint/permisos/conectar", json={"url": URL}).json()
    assert sup.put("/api/sharepoint/permisos", json={"activo": True, "mapeo": cfg["mapeo"], "valores": cfg["valores"],
                                                      **TEAMS}).status_code == 200
    try:
        _flujo(entorno, "Jefe → GH (Teams)", [{"aprobador": "jefe"}, {"aprobador": "gh"}])
        p = _pedir(maria, entorno, date(2031, 6, 2))
        sharepoint.procesar_pendientes()
        item = next(k for k, v in graph["items"].items() if v["Title"] == f"PER-{p['id']}")
        jefa = laura.get("/api/auth/me").json()["email"]
        assert graph["items"][item]["CorreoJefe"] == jefa  # la tarjeta va a quien aprueba el paso actual
        graph["items"][item].update({"Decision": "Approve", "Respondio": jefa})
        assert sharepoint.revisar_decisiones() == 1
        r = adm.get(f"/api/permisos/{p['id']}").json()
        assert r["estado"] == "solicitado" and r["paso_actual"] == "GH de la sede" and r["pasos"][0]["canal"] == "teams"
        # La misma decisión no se vuelve a aplicar al paso de GH: ese se resuelve en SIP-O
        assert sharepoint.revisar_decisiones() == 0
        assert adm.get(f"/api/permisos/{p['id']}").json()["estado"] == "solicitado"
    finally:
        sup.delete("/api/sharepoint/permisos")
