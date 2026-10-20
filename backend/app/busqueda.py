"""Búsqueda de empleados por palabras, sin distinguir mayúsculas ni acentos (servicio médico y caseta)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Usuario
from .sedes import normalizar


def buscar_usuarios(db: Session, sede_ids, q: str | None, *, excluir_id: int | None = None, rol: str | None = None,
                    limite: int = 30) -> list[Usuario]:
    """Empleados activos de esas sedes cuyo nombre, nómina, puesto, departamento o correo contienen todas las palabras.

    Orden: nómina exacta, nombre que empieza igual, alguna palabra del nombre que empieza igual y el resto."""
    stmt = select(Usuario).where(Usuario.activo.is_(True), Usuario.sede_id.in_([x for x in sede_ids if x is not None] or [-1]))
    if excluir_id:
        stmt = stmt.where(Usuario.id != excluir_id)
    if rol:
        stmt = stmt.where(Usuario.rol == rol)
    palabras = normalizar(q).split()
    frase = " ".join(palabras)
    res = []
    for u in db.scalars(stmt.order_by(Usuario.nombre)):
        nombre = normalizar(u.nombre)
        texto = " ".join(normalizar(x) for x in (u.nombre, u.numero_empleado, u.puesto, u.departamento, u.email, u.email_personal) if x)
        if not all(w in texto for w in palabras):
            continue
        orden = (0 if palabras and normalizar(u.numero_empleado) == frase else 1 if nombre.startswith(frase)
                 else 2 if palabras and any(n.startswith(palabras[0]) for n in nombre.split()) else 3)
        res.append((orden, nombre, u))
    return [u for _, _, u in sorted(res, key=lambda x: (x[0], x[1]))[:max(1, min(limite, 100))]]
