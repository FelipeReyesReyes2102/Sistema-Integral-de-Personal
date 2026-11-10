"""SharePoint: un tipo de permiso puede tener su propia lista; los demás siguen yendo a la lista de permisos."""
from datetime import date, timedelta

from app import sharepoint
from app import tipos_permiso as tp
from app.database import SessionLocal
from app.models import EnvioSharePoint, Permiso
from app.sedes import sede_principal
from tests.test_api import FIRMA, login
from tests.test_sharepoint import URL, graph, super_login  # noqa: F401 (fixture)


def _permiso(cliente, tipo, dia, hi, hf):
    r = cliente.post("/api/permisos", json={"tipo": tipo, "fecha": str(dia), "hora_inicio": hi, "hora_fin": hf,
                                           "motivo": "Prueba SharePoint", "tipo_nomina": "con_goce", "enviar": True,
                                           "firma": FIRMA})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _lista_de(pid):
    with SessionLocal() as db:
        return {e.lista_id for e in db.query(EnvioSharePoint).filter(EnvioSharePoint.registro_id == pid)}


def test_lista_propia_por_tipo_de_permiso(graph):
    adm, ana = super_login(), login("ana@empresa.com", "Cambiar123")
    with SessionLocal() as db:
        tid = next(t.id for t in tp.de_sede(db, sede_principal(db).id) if t.clave == "salida_temprana")
        db.commit()  # de_sede crea los tipos base si la sede aún no los tiene
    propia = sharepoint.tipo_de_lista(tid)

    # Lista general de permisos y lista propia de «Salida temprana»
    for tipo in ("permisos", propia):
        r = adm.put(f"/api/sharepoint/{tipo}/conectar", json={"url": URL})
        assert r.status_code == 200, (tipo, r.text)
        cfg = r.json()
        r = adm.put(f"/api/sharepoint/{tipo}", json={"activo": True, "mapeo": {"Title": "folio", "Estatus": "estado"},
                                                     "valores": cfg["valores"]})
        assert r.status_code == 200, r.text
    estado = adm.get("/api/sharepoint").json()
    assert estado["listas"][propia]["nombre"] == "Salida temprana" and estado["listas"][propia]["conectada"]
    assert any(t["tipo"] == propia for t in estado["tipos_permiso"])
    assert adm.put("/api/sharepoint/p999999/conectar", json={"url": URL}).status_code == 404
    id_general, id_propia = estado["listas"]["permisos"], estado["listas"][propia]

    with SessionLocal() as db:
        from app.models import ListaSharePoint
        lid = {l.tipo: l.id for l in db.query(ListaSharePoint).filter(ListaSharePoint.tipo.in_(["permisos", propia]))}

    dia = date.today() + timedelta(weeks=33)
    dia -= timedelta(days=dia.weekday() - 2) if dia.weekday() > 2 else timedelta(days=0)
    p_salida = _permiso(ana, "salida_temprana", dia, "15:00", "17:00")
    p_tarde = _permiso(ana, "llegada_tarde", dia + timedelta(days=7), "08:00", "09:00")
    assert _lista_de(p_salida) == {lid[propia]}
    assert _lista_de(p_tarde) == {lid["permisos"]}
    sharepoint.procesar_pendientes()
    assert {v["Title"] for v in graph["items"].values()} >= {f"PER-{p_salida}", f"PER-{p_tarde}"}

    # Historial: cada lista toma solo lo suyo
    with SessionLocal() as db:
        db.query(EnvioSharePoint).filter(EnvioSharePoint.registro_id.in_([p_salida, p_tarde])).delete()
        db.commit()
    adm.post("/api/sharepoint/permisos/existentes", json={"desde": str(dia - timedelta(days=1))})
    adm.post(f"/api/sharepoint/{propia}/existentes", json={"desde": str(dia - timedelta(days=1))})
    assert _lista_de(p_salida) == {lid[propia]} and _lista_de(p_tarde) == {lid["permisos"]}

    for pid in (p_salida, p_tarde):
        ana.post(f"/api/permisos/{pid}/cancelar")
    for tipo in (propia, "permisos"):
        assert adm.delete(f"/api/sharepoint/{tipo}").json()["conectada"] is False
    assert id_general and id_propia
    with SessionLocal() as db:
        for pid in (p_salida, p_tarde):
            db.query(Permiso).filter(Permiso.id == pid).delete()
        db.commit()
