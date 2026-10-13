"""Migración ligera: crea tablas nuevas, agrega columnas que falten y vuelve opcionales (NULL)
las columnas que el modelo ya no exige.

Evita perder datos cuando se agregan o relajan campos del modelo. Para cambios más complejos
(renombrar o borrar columnas) conviene adoptar Alembic.
"""
from sqlalchemy import Table, inspect, text
from sqlalchemy.engine import Connection, Engine

from .database import Base


def actualizar_esquema(engine: Engine) -> list[str]:
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    agregadas: list[str] = []
    with engine.begin() as conn:
        for tabla in Base.metadata.sorted_tables:
            columnas = {c["name"]: c for c in insp.get_columns(tabla.name)}
            for col in tabla.columns:
                if col.name in columnas:
                    continue
                tipo = col.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE {tabla.name} ADD COLUMN {col.name} {tipo}'
                if col.server_default is not None:
                    default = col.server_default.arg
                    if not isinstance(default, str):
                        default = default.compile(dialect=engine.dialect)
                    ddl += f" DEFAULT {default}"
                conn.execute(text(ddl))
                agregadas.append(f"{tabla.name}.{col.name}")

            # Columnas que ahora aceptan NULL (p. ej. el correo corporativo, que planta no tiene)
            relajar = [c.name for c in tabla.columns
                       if c.name in columnas and c.nullable and not c.primary_key and not columnas[c.name]["nullable"]]
            if relajar:
                if engine.dialect.name == "sqlite":
                    _reconstruir_sqlite(conn, tabla, list(columnas))
                else:
                    for nombre in relajar:
                        conn.execute(text(f"ALTER TABLE {tabla.name} ALTER COLUMN {nombre} DROP NOT NULL"))
                agregadas += [f"{tabla.name}.{n} (opcional)" for n in relajar]

        # Índices nuevos (p. ej. el índice único de usuarios.microsoft_oid)
        for tabla in Base.metadata.sorted_tables:
            for indice in tabla.indexes:
                indice.create(conn, checkfirst=True)

        _migrar_datos(conn, agregadas, insp)
    return agregadas


def _reconstruir_sqlite(conn: Connection, tabla: Table, columnas_actuales: list[str]):
    """SQLite no permite quitar NOT NULL: se recrea la tabla con la definición del modelo y se copian los datos."""
    tmp = f"{tabla.name}__anterior"
    conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")  # que las llaves foráneas de otras tablas no se renombren
    conn.exec_driver_sql(f'ALTER TABLE "{tabla.name}" RENAME TO "{tmp}"')
    for (nombre,) in conn.exec_driver_sql(
            f"SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='{tmp}' AND sql IS NOT NULL").fetchall():
        conn.exec_driver_sql(f'DROP INDEX "{nombre}"')
    tabla.create(conn)
    comunes = ", ".join(f'"{c.name}"' for c in tabla.columns if c.name in columnas_actuales)
    conn.exec_driver_sql(f'INSERT INTO "{tabla.name}" ({comunes}) SELECT {comunes} FROM "{tmp}"')
    conn.exec_driver_sql(f'DROP TABLE "{tmp}"')
    conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")


SEDE_INICIAL = "O-tek México"


def _migrar_datos(conn: Connection, agregadas: list[str], insp=None):
    """Ajustes de datos que se ejecutan una sola vez, cuando aparece la columna correspondiente."""
    if "usuarios.sede_id" in agregadas:
        _migrar_sedes(conn, insp)
    if "usuarios.email_personal" in agregadas:
        # Planta no tiene correo corporativo: el correo que tenían pasa a ser su correo personal
        conn.execute(text("UPDATE usuarios SET email_personal = email, email = NULL WHERE rol = 'planta' AND email IS NOT NULL"))


def _migrar_sedes(conn: Connection, insp):
    """Sedes: todo lo que ya existía pasa a la sede inicial (México), incluida la configuración de caseta;
    los nombres de turnos y grupos dejan de ser únicos globalmente y pasan a ser únicos por sede."""
    from .models import Grupo, Sede, Turno

    sedes = Sede.__table__
    sede_id = conn.execute(text("SELECT id FROM sedes WHERE nombre = :n"), {"n": SEDE_INICIAL}).scalar()
    if sede_id is None:
        caseta = dict(conn.execute(text(
            "SELECT clave, valor FROM configuracion WHERE clave IN "
            "('CORREO_CASETA_ACTIVO', 'CORREO_CASETA_DESTINATARIOS', 'CORREO_CASETA_TIPOS')")).all())
        sede_id = conn.execute(sedes.insert().values(
            nombre=SEDE_INICIAL, ubicacion_microsoft=SEDE_INICIAL, zona_horaria="America/Mexico_City", activa=True,
            caseta_activo=caseta.get("CORREO_CASETA_ACTIVO") == "true",
            caseta_destinatarios=caseta.get("CORREO_CASETA_DESTINATARIOS") or "",
            caseta_tipos=caseta.get("CORREO_CASETA_TIPOS") or "llegada_tarde,salida_temprana,salida_intermedia",
        )).inserted_primary_key[0]
    for tabla in ("usuarios", "turnos", "grupos", "festivos", "rotacion_turnos", "notificaciones_correo"):
        conn.execute(text(f"UPDATE {tabla} SET sede_id = :s WHERE sede_id IS NULL"), {"s": sede_id})

    # Nombre único por sede (antes era único en toda la aplicación)
    for modelo in (Turno, Grupo):
        tabla = modelo.__table__
        if conn.dialect.name == "sqlite":
            columnas = [c["name"] for c in inspect(conn).get_columns(tabla.name)]
            _reconstruir_sqlite(conn, tabla, columnas)
            continue
        for uc in insp.get_unique_constraints(tabla.name):
            if uc["column_names"] == ["nombre"]:
                conn.execute(text(f'ALTER TABLE {tabla.name} DROP CONSTRAINT "{uc["name"]}"'))
        for ix in insp.get_indexes(tabla.name):
            if ix.get("unique") and ix["column_names"] == ["nombre"]:
                conn.execute(text(f'DROP INDEX IF EXISTS "{ix["name"]}"'))
        conn.execute(text(f"ALTER TABLE {tabla.name} ADD CONSTRAINT uq_{tabla.name}_sede_nombre UNIQUE (sede_id, nombre)"))
