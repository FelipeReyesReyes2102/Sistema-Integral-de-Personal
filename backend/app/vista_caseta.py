"""Lo que ve el personal de caseta: solo el permiso y el nombre corto de la persona.

Al rol caseta no le llegan el número de nómina, el puesto, el departamento ni el correo de los empleados, y los
nombres se reducen a primer nombre y primer apellido ("Felipe De Jesus Reyes Reyes" → "Felipe Reyes"). Se aplica a
las respuestas de /api/caseta y /api/equipos (ver el middleware en main.py), así que cubre también los textos
guardados antes de este cambio.
"""
# Datos personales que caseta no necesita para validar un permiso
OCULTOS = {"numero_empleado", "puesto", "departamento", "email", "email_personal", "telefono",
           "usuario_numero", "usuario_departamento", "usuario_puesto", "usuario_email"}
# Campos que siempre contienen el nombre de una persona
NOMBRES = {"usuario_nombre", "autorizo", "aprobador_nombre", "registrado_por", "revisado_por_nombre", "ti_por_nombre",
           "salida_por_nombre", "regreso_por_nombre", "jefe_nombre"}
# "nombre" es de una persona cuando el objeto la describe (no un tipo de permiso, una sede, etc.)
MARCAS_PERSONA = {"usuario_id", "numero_empleado", "tiene_foto"}
PARTICULAS = {"de", "del", "la", "las", "los", "y", "san", "santa", "da", "di", "van", "von", "mc"}


def nombre_corto(nombre: str | None) -> str | None:
    """Primer nombre y primer apellido. Supone el orden habitual: nombre(s) y luego dos apellidos."""
    if not nombre:
        return nombre
    p = nombre.split()
    if len(p) <= 2:
        return " ".join(p)
    if len(p) == 3:  # "Juan Pérez García"
        return f"{p[0]} {p[1]}"
    # Nombre(s) + dos apellidos: el primer apellido es el penúltimo, con sus partículas ("De la Cruz")
    i = len(p) - 2
    while i - 1 > 0 and p[i - 1].lower() in PARTICULAS:
        i -= 1
    return f"{p[0]} {' '.join(p[i:-1])}"


def _juntar(obj, nombres: set[str]):
    if isinstance(obj, dict):
        es_persona = bool(MARCAS_PERSONA & obj.keys())
        for k, v in obj.items():
            if isinstance(v, str) and (k in NOMBRES or (k == "nombre" and es_persona)):
                for n in v.split(", "):
                    if len(n.split()) > 2:
                        nombres.add(n.strip())
            else:
                _juntar(v, nombres)
    elif isinstance(obj, list):
        for x in obj:
            _juntar(x, nombres)


def _limpiar(obj, cambios: list[tuple[str, str]]):
    if isinstance(obj, dict):
        es_persona = bool(MARCAS_PERSONA & obj.keys())
        res = {}
        for k, v in obj.items():
            if k in OCULTOS:
                continue
            if isinstance(v, str) and (k in NOMBRES or (k == "nombre" and es_persona)):
                res[k] = ", ".join(nombre_corto(n.strip()) for n in v.split(", "))
            else:
                res[k] = _limpiar(v, cambios)
        return res
    if isinstance(obj, list):
        return [_limpiar(x, cambios) for x in obj]
    if isinstance(obj, str) and cambios:
        for completo, corto in cambios:
            if completo in obj:
                obj = obj.replace(completo, corto)
        return obj
    return obj


def limpiar(datos):
    """Quita los datos personales y acorta los nombres, también dentro de mensajes y notas."""
    nombres: set[str] = set()
    _juntar(datos, nombres)
    cambios = sorted(((n, nombre_corto(n)) for n in nombres), key=lambda x: -len(x[0]))  # primero los más largos
    return _limpiar(datos, cambios)


def texto_corto(nombre: str | None) -> str:
    """Para mensajes que se arman en el servidor (errores y notas de caseta)."""
    return nombre_corto(nombre) or ""

