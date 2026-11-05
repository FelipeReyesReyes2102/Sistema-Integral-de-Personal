"""Jefes del grupo de planta: cualquiera ve a los integrantes en Mi equipo y aprueba sus solicitudes."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Grupo, GrupoJefe, Usuario
from app.security import hash_password
from app.sedes import sede_principal
from app.seed import main as seed
from tests.test_api import FIRMA
from tests.test_consultas import entrar

seed()
PWD = "Clave12345"


def _mundo():
    with SessionLocal() as db:
        sede = sede_principal(db).id
        g = db.query(Grupo).filter(Grupo.nombre == "Grupo con jefes").first()
        if g is None:
            g = Grupo(nombre="Grupo con jefes", sede_id=sede, tipo_ciclo="semanal", dias_semana="0,1,2,3,4")
            db.add(g)
            db.commit()
        db.query(GrupoJefe).filter(GrupoJefe.grupo_id == g.id).delete()

        def usuario(nomina, nombre, rol="oficina", es_jefe=False):
            u = db.query(Usuario).filter(Usuario.numero_empleado == nomina).first()
            if u is None:
                u = Usuario(numero_empleado=nomina, nombre=nombre, email=f"{nomina.lower()}@o-tek.com", rol=rol,
                            es_jefe=es_jefe, password_hash=hash_password(PWD), fecha_ingreso=date(2018, 1, 8), sede_id=sede)
                db.add(u)
                db.flush()
            return u.id
        ids = {"j1": usuario("GJ-1", "Ana Jefa Turno 1", es_jefe=True), "j2": usuario("GJ-2", "Beto Jefe Turno 2", es_jefe=True),
               "otro": usuario("GJ-3", "Ciro Jefe Ajeno", es_jefe=True), "noj": usuario("GJ-4", "Dora Sin Jefatura"),
               "emp": usuario("GJ-5", "Eva Operadora", rol="planta")}
        emp = db.get(Usuario, ids["emp"])
        emp.grupo_id, emp.jefe_id = g.id, None
        db.commit()
        return g.id, ids


def test_jefes_del_grupo():
    gid, ids = _mundo()
    admin = entrar("admin@empresa.com", "Admin123")
    # Solo pueden ser jefes del grupo quienes están marcados como jefe en la sede
    r = admin.put(f"/api/grupos/{gid}/jefes", json={"usuario_ids": [ids["j1"], ids["noj"]]})
    assert r.status_code == 400 and "Dora" in r.text
    r = admin.put(f"/api/grupos/{gid}/jefes", json={"usuario_ids": [ids["j1"], ids["j2"]]})
    assert r.status_code == 200, r.text
    assert [j["nombre"] for j in r.json()["jefes"]] == ["Ana Jefa Turno 1", "Beto Jefe Turno 2"]

    eva = entrar("gj-5@o-tek.com", PWD)
    me = eva.get("/api/auth/me").json()
    assert set(me["jefes_grupo"]) == {ids["j1"], ids["j2"]} and me["jefe_id"] is None
    # Sin jefe directo, su solicitud va por omisión al primer jefe del grupo
    periodo = next(p for p in eva.get("/api/periodos").json() if p["vigente"] and p["dias_disponible"] >= 1)
    dia = date.today() + timedelta(days=30)
    for _ in range(30):
        calc = eva.post("/api/vacaciones/calcular", json={"periodo_id": periodo["id"], "fecha_inicio": str(dia),
                                                           "fecha_fin": str(dia)}).json()
        if not calc["errores"] and calc["dias_habiles"] == 1:
            break
        dia += timedelta(days=1)
    r = eva.post("/api/vacaciones", json={"periodo_id": periodo["id"], "fecha_inicio": str(dia), "fecha_fin": str(dia),
                                          "enviar": True, "firma": FIRMA})
    if r.status_code == 422 and "seguidos" in r.text:  # política de bloque mínimo: basta con un borrador
        r = eva.post("/api/vacaciones", json={"periodo_id": periodo["id"], "fecha_inicio": str(dia), "fecha_fin": str(dia)})
    assert r.status_code == 201, r.text
    sol = r.json()
    assert sol["aprobador_id"] == ids["j1"]

    beto, ciro = entrar("gj-2@o-tek.com", PWD), entrar("gj-3@o-tek.com", PWD)
    # El otro jefe del grupo la ve, la cuenta y tiene a Eva en Mi equipo; un jefe ajeno no
    assert ids["emp"] in [m["usuario"]["id"] for m in beto.get("/api/equipo").json()]
    assert ids["emp"] not in [m["usuario"]["id"] for m in ciro.get("/api/equipo").json()]
    assert beto.get(f"/api/vacaciones/{sol['id']}").status_code == 200
    assert ciro.get(f"/api/vacaciones/{sol['id']}").status_code == 404
    assert beto.get(f"/api/periodos?usuario_id={ids['emp']}").status_code == 200
    if sol["estado"] == "solicitado":
        assert sol["id"] in [s["id"] for s in beto.get("/api/vacaciones?por_aprobar=true").json()]
        assert beto.get("/api/pendientes").json()["vacaciones"] >= 1
        assert ciro.post(f"/api/vacaciones/{sol['id']}/validar").status_code in (403, 404)
        assert beto.post(f"/api/vacaciones/{sol['id']}/validar").json()["estado"] == "validado"
    # Quitar los jefes del grupo deja de dar acceso
    assert admin.put(f"/api/grupos/{gid}/jefes", json={"usuario_ids": []}).json()["jefes"] == []
    assert ids["emp"] not in [m["usuario"]["id"] for m in beto.get("/api/equipo").json()]


def test_areas_con_sus_jefes():
    gid, ids = _mundo()
    admin = entrar("admin@empresa.com", "Admin123")
    admin.put(f"/api/grupos/{gid}/jefes", json={"usuario_ids": [ids["j1"]]})
    with SessionLocal() as db:
        for sg in db.get(Grupo, gid).subgrupos:
            db.delete(sg)
        db.commit()
    r = admin.post(f"/api/grupos/{gid}/subgrupos", json={"nombre": "Calidad"})
    assert r.status_code == 201, r.text
    assert admin.post(f"/api/grupos/{gid}/subgrupos", json={"nombre": "Calidad"}).status_code == 409
    area = next(a for a in r.json()["subgrupos"] if a["nombre"] == "Calidad")
    # Solo integrantes del grupo; jefes válidos de la sede
    assert admin.put(f"/api/subgrupos/{area['id']}/miembros", json={"usuario_ids": [ids["noj"]]}).status_code == 400
    assert admin.put(f"/api/subgrupos/{area['id']}/jefes", json={"usuario_ids": [ids["noj"]]}).status_code == 400
    admin.put(f"/api/subgrupos/{area['id']}/jefes", json={"usuario_ids": [ids["otro"]]})
    r = admin.put(f"/api/subgrupos/{area['id']}/miembros", json={"usuario_ids": [ids["emp"]]})
    a = next(x for x in r.json()["subgrupos"] if x["id"] == area["id"])
    assert a["total_miembros"] == 1 and [j["nombre"] for j in a["jefes"]] == ["Ciro Jefe Ajeno"]

    # Eva (área Calidad) queda con el jefe del área, ya no con el del grupo
    me = entrar("gj-5@o-tek.com", PWD).get("/api/auth/me").json()
    assert me["jefes_grupo"] == [ids["otro"]] and me["subgrupo_nombre"] == "Calidad"
    ana, ciro = entrar("gj-1@o-tek.com", PWD), entrar("gj-3@o-tek.com", PWD)
    assert ids["emp"] in [m["usuario"]["id"] for m in ciro.get("/api/equipo").json()]
    assert ids["emp"] not in [m["usuario"]["id"] for m in ana.get("/api/equipo").json()]
    # Al borrar el área vuelve con los jefes del grupo
    admin.delete(f"/api/subgrupos/{area['id']}")
    assert ids["emp"] in [m["usuario"]["id"] for m in ana.get("/api/equipo").json()]
    assert ids["emp"] not in [m["usuario"]["id"] for m in ciro.get("/api/equipo").json()]
