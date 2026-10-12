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

        _migrar_datos(conn, agregadas)
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


def _migrar_datos(conn: Connection, agregadas: list[str]):
    """Ajustes de datos que se ejecutan una sola vez, cuando aparece la columna correspondiente."""
    if "usuarios.email_personal" in agregadas:
        # Planta no tiene correo corporativo: el correo que tenían pasa a ser su correo personal
        conn.execute(text("UPDATE usuarios SET email_personal = email, email = NULL WHERE rol = 'planta' AND email IS NOT NULL"))
