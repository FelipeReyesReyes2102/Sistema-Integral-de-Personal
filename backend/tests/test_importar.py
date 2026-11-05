"""Importar empleados desde Excel: vista previa sin guardar, alta con contraseña inicial y días adeudados por periodo."""
import io
import zipfile
from datetime import date

from fastapi.testclient import TestClient

from app import importacion
from app.database import SessionLocal
from app.main import app
from app.models import Usuario
from app.seed import main as seed
from tests.test_consultas import entrar

seed()
HOY = date.today()


def _xlsx(filas) -> bytes:
    """Excel mínimo (cadenas en línea y números) para las pruebas."""
    def celda(ref, v):
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    xml = "".join(f'<row r="{i}">' + "".join(celda(f"{chr(65 + j)}{i}", v) for j, v in enumerate(f)) + "</row>"
                  for i, f in enumerate(filas, 1))
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="H" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   f"<sheetData>{xml}</sheetData></worksheet>")
    return b.getvalue()


def _serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def _archivo():
    hace = lambda anios: _serial(date(HOY.year - anios, HOY.month, 1))  # noqa: E731
    return _xlsx([
        ["O-TEK MEXICO"], ["Vacaciones adeudadas"], [],
        ["Código", "Empleado", "Fecha de ingreso", f"Periodo {HOY.year - 1}-{HOY.year}", f"Periodo {HOY.year - 2}-{HOY.year - 1}", "Comentarios"],
        ["9001", "PEREZ LOPEZ JUAN", hace(5), 10, 0, ""],
        ["9002", "GARCIA  ANA", hace(3), "7+8 horas", 0, "Días de 12 horas"],
        ["9003", "NUEVO RECIENTE", _serial(HOY), 0, 0, ""],
        ["0001", "YA EXISTE", hace(5), 0, 0, ""],
        ["9004", "SIN FECHA", None, 0, 0, ""],
        [89, "Empresa"],
    ])


def _enviar(c, aplicar, password=""):
    return c.post("/api/usuarios/importar", files={"archivo": ("emp.xlsx", _archivo())},
                  data={"aplicar": "true" if aplicar else "false", "password": password})


def test_saldo_y_lectura():
    assert importacion.nombre_ordenado("SOTO DE ANDA XIMENA GERALDINE") == "Ximena Geraldine Soto de Anda"
    assert importacion.nombre_ordenado("DE LARA SANTANA JORGE") == "Jorge de Lara Santana"
    assert importacion.nombre_ordenado("REYES REYES FELIPE DE JESUS") == "Felipe de Jesus Reyes Reyes"
    assert importacion.nombre_ordenado("MARTINEZ  LUIS FERNANDO") == "Luis Fernando Martinez"
    assert importacion.saldo("7+8 horas") == (7, 8) and importacion.saldo(26.0) == (26, 0) and importacion.saldo(None) == (0, 0)
    filas, periodos = importacion.interpretar(importacion.leer_xlsx(_archivo()))
    assert [f.nomina for f in filas] == ["9001", "9002", "9003", "0001", "9004"]  # sin la fila de totales
    assert filas[1].nombre == "Ana Garcia" and filas[1].planta and not filas[0].planta
    assert periodos[0].startswith(f"Periodo {HOY.year - 1}")


def test_importar_vista_previa_y_alta():
    admin = entrar("admin@empresa.com", "Admin123")
    with SessionLocal() as db:
        db.query(Usuario).filter(Usuario.numero_empleado.in_(["9001", "9002", "9003"])).delete()
        ya = db.query(Usuario).filter(Usuario.numero_empleado == "0001").one()
        nombre_antes = ya.nombre
        db.commit()

    r = _enviar(admin, False)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["resumen"] == {"nuevo": 3, "existe": 1, "error": 1} and not d["aplicado"]
    with SessionLocal() as db:  # la vista previa no guarda nada
        assert db.query(Usuario).filter(Usuario.numero_empleado == "9001").count() == 0
    assert _enviar(admin, True, "corta").status_code == 422

    r = _enviar(admin, True, "Inicial*2026")
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        juan = db.query(Usuario).filter(Usuario.numero_empleado == "9001").one()
        assert juan.rol == "oficina" and juan.email is None and juan.debe_cambiar_password and juan.nombre == "Juan Perez Lopez"
        ana = db.query(Usuario).filter(Usuario.numero_empleado == "9002").one()
        assert ana.rol == "planta"
        assert db.query(Usuario).filter(Usuario.numero_empleado == "0001").one().nombre == nombre_antes  # no se toca
        ids = juan.id, ana.id

    # Entra con su nómina y la contraseña inicial; los días adeudados quedan en el periodo actual
    c = TestClient(app)
    assert c.post("/api/auth/login-json", json={"usuario": "9001", "password": "Inicial*2026"}).status_code == 200
    juan_p = [p for p in admin.get("/api/periodos", params={"usuario_id": ids[0]}).json() if p["vigente"]]
    assert max(juan_p, key=lambda p: p["fecha_inicio"])["dias_disponible"] == 10
    ana_p = max((p for p in admin.get("/api/periodos", params={"usuario_id": ids[1]}).json() if p["vigente"]),
                key=lambda p: p["fecha_inicio"])
    assert round(ana_p["horas_disponible"], 2) == 7 * ana_p["horas_por_dia"] + 8

    # Volver a importar no duplica a nadie
    assert _enviar(admin, False).json()["resumen"]["existe"] == 4
