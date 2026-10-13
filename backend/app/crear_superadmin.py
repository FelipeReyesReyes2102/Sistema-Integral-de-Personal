"""Crea (o promueve) un super administrador.

Uso:
    python -m app.crear_superadmin --email nombre@o-tek.com --nombre "Nombre" --nomina 0001

La contraseña se toma de la variable de entorno SUPERADMIN_PASSWORD o se pide por consola;
nunca se guarda en el código ni en archivos del proyecto.
"""
import argparse
import getpass
import os
from datetime import date

from sqlalchemy import func, select

from .database import SessionLocal, engine
from .migraciones import actualizar_esquema
from .models import ROL_SUPERADMIN, Usuario
from .security import auditar, hash_password
from .sedes import sede_principal
from .services import sincronizar_periodos


def main():
    ap = argparse.ArgumentParser(description="Crear o promover un super administrador")
    ap.add_argument("--email", required=True)
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--nomina", required=True, help="Número de nómina (también sirve para iniciar sesión)")
    ap.add_argument("--ingreso", default=None, help="Fecha de ingreso AAAA-MM-DD (por defecto hoy)")
    a = ap.parse_args()

    password = os.environ.get("SUPERADMIN_PASSWORD") or getpass.getpass("Contraseña del super administrador: ")
    if len(password) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 caracteres.")

    actualizar_esquema(engine)
    email = a.email.strip().lower()
    with SessionLocal() as db:
        u = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))
        accion = "promovido"
        if u is None:
            otro = db.scalar(select(Usuario).where(Usuario.numero_empleado == a.nomina))
            if otro:
                raise SystemExit(f"El número de nómina {a.nomina} ya pertenece a {otro.nombre}.")
            u = Usuario(sede_id=sede_principal(db).id, email=email, numero_empleado=a.nomina, nombre=a.nombre,
                        fecha_ingreso=date.fromisoformat(a.ingreso) if a.ingreso else date.today(),
                        puesto="Super administrador", departamento="Sistemas")
            db.add(u)
            accion = "creado"
        u.rol, u.activo, u.es_jefe = ROL_SUPERADMIN, True, True
        u.password_hash = hash_password(password)
        db.flush()
        auditar(db, "superadmin_" + accion, usuario_id=u.id, detalle=email)
        db.commit()
        sincronizar_periodos(db, u)
        print(f"Super administrador {accion}: {u.nombre} <{u.email}> · nómina {u.numero_empleado}")


if __name__ == "__main__":
    main()
