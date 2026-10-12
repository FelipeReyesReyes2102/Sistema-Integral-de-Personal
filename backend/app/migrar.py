"""Aplica las migraciones del esquema de forma controlada (fuera del arranque normal).

Uso (producción):  docker compose -p sip-o run --rm api python -m app.migrar
"""
import sys

from . import models  # noqa: F401 - registra todas las tablas
from .database import engine
from .migraciones import actualizar_esquema


def main() -> int:
    cambios = actualizar_esquema(engine)
    if cambios:
        print("Migración aplicada:")
        for c in cambios:
            print(f"  - {c}")
    else:
        print("El esquema ya estaba al día; no hubo cambios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
