"""Carga datos iniciales: tabla de antigüedad, turnos, grupos, festivos y usuarios de ejemplo.

Uso:
    python -m app.seed                   # catálogos + usuarios de ejemplo (desarrollo y pruebas)
    python -m app.seed --solo-catalogos  # solo catálogos, sin usuarios (producción)
"""
import argparse
from datetime import date, time

from sqlalchemy import select

from . import reglas
from .database import SessionLocal, engine
from .migraciones import actualizar_esquema
from .models import Festivo, Grupo, ReglaAntiguedad, RotacionTurnos, Turno, Usuario
from .security import hash_password
from .sedes import sede_principal
from .services import sincronizar_periodos


def festivos_mexico(anio: int) -> list[tuple[date, str]]:
    def n_lunes(mes: int, n: int) -> date:
        d = date(anio, mes, 1)
        while d.weekday() != 0:
            d = date(anio, mes, d.day + 1)
        return date(anio, mes, d.day + 7 * (n - 1))

    return [
        (date(anio, 1, 1), "Año Nuevo"),
        (n_lunes(2, 1), "Día de la Constitución"),
        (n_lunes(3, 3), "Natalicio de Benito Juárez"),
        (date(anio, 5, 1), "Día del Trabajo"),
        (date(anio, 9, 16), "Día de la Independencia"),
        (n_lunes(11, 3), "Revolución Mexicana"),
        (date(anio, 12, 25), "Navidad"),
    ]


def main(solo_catalogos: bool = False):
    actualizar_esquema(engine)
    db = SessionLocal()
    try:
        if not db.scalar(select(ReglaAntiguedad.id).limit(1)):
            for desde, hasta, dias in reglas.TABLA_ANTIGUEDAD_DEFAULT:
                db.add(ReglaAntiguedad(anios_desde=desde, anios_hasta=hasta, dias=dias))

        if not db.scalar(select(Turno.id).limit(1)):
            db.add_all([
                Turno(nombre="Oficina", hora_entrada=time(8), hora_salida=time(17), horas_jornada=8,
                      descripcion="Lunes a viernes 8:00 - 17:00"),
                Turno(nombre="Día", hora_entrada=time(7), hora_salida=time(19), horas_jornada=12,
                      descripcion="Turno diurno de 12 h"),
                Turno(nombre="Noche", hora_entrada=time(19), hora_salida=time(7), horas_jornada=12,
                      descripcion="Turno nocturno de 12 h"),
            ])

        if not db.scalar(select(Grupo.id).limit(1)):
            base = date(2024, 1, 1)
            db.add_all([
                Grupo(nombre="Grupo A", tipo_ciclo="rotativo", dias_trabajo=4, dias_descanso=4,
                      fecha_inicio_ciclo=base, color="#1976d2", descripcion="4x4 inicia 01/01/2024"),
                Grupo(nombre="Grupo B", tipo_ciclo="rotativo", dias_trabajo=4, dias_descanso=4,
                      fecha_inicio_ciclo=date(2024, 1, 5), color="#2e7d32", descripcion="4x4 inicia 05/01/2024"),
                Grupo(nombre="Grupo C", tipo_ciclo="semanal", dias_semana="0,1,2,3", color="#ef6c00",
                      descripcion="Lunes a jueves"),
            ])

        anio = date.today().year
        sede = sede_principal(db)
        if not db.scalar(select(Festivo.id).limit(1)):
            for a in (anio - 1, anio, anio + 1):
                for f, nombre in festivos_mexico(a):
                    db.add(Festivo(fecha=f, nombre=nombre, aplica_a="todos"))
        db.commit()
        _asignar_sede(db, sede.id)
        if solo_catalogos:
            print("Catálogos cargados (antigüedad, turnos, grupos y festivos). No se crearon usuarios.")
            print("Crea el super administrador con: python -m app.crear_superadmin --email ... --nombre ... --nomina ...")
            return

        if not db.scalar(select(Usuario.id).limit(1)):
            turnos = {t.nombre: t for t in db.scalars(select(Turno))}
            grupos = {g.nombre: g for g in db.scalars(select(Grupo))}
            pwd = hash_password("Cambiar123")
            usuarios = [
                Usuario(numero_empleado="0001", nombre="Administrador RH", email="admin@empresa.com",
                        password_hash=hash_password("Admin123"), rol="admin", fecha_ingreso=date(2018, 3, 1),
                        puesto="Recursos Humanos", departamento="RH", turno_id=turnos["Oficina"].id),
                Usuario(numero_empleado="1001", nombre="Ana López", email="ana@empresa.com", password_hash=pwd,
                        rol="oficina", fecha_ingreso=date(anio - 3, 2, 15), puesto="Analista",
                        departamento="Finanzas", turno_id=turnos["Oficina"].id),
                Usuario(numero_empleado="2001", nombre="Carlos Pérez", email_personal="carlos@empresa.com",
                        password_hash=pwd, rol="planta", fecha_ingreso=date(anio - 2, 1, 10),
                        puesto="Operador", departamento="Producción", turno_id=turnos["Día"].id,
                        grupo_id=grupos["Grupo A"].id),
                Usuario(numero_empleado="2002", nombre="María Gómez", email_personal="maria@empresa.com",
                        password_hash=pwd, rol="planta", fecha_ingreso=date(anio - 6, 6, 1),
                        puesto="Técnico", departamento="Mantenimiento", turno_id=turnos["Noche"].id,
                        grupo_id=grupos["Grupo B"].id),
            ]
            for u in usuarios:
                u.sede_id = sede.id
            db.add_all(usuarios)
            db.commit()
            for u in usuarios:
                sincronizar_periodos(db, u)

        # Jefes y líneas de reporte de ejemplo (idempotente)
        if not db.scalar(select(Usuario.id).where(Usuario.email == "laura@empresa.com")):
            turno_oficina = db.scalar(select(Turno).where(Turno.nombre == "Oficina"))
            laura = Usuario(numero_empleado="0500", nombre="Laura Martínez", email="laura@empresa.com",
                            password_hash=hash_password("Cambiar123"), rol="oficina", es_jefe=True,
                            fecha_ingreso=date(anio - 8, 4, 1), puesto="Gerente de Producción",
                            departamento="Producción", turno_id=turno_oficina.id if turno_oficina else None)
            db.add(laura)
            db.flush()
            por_email = {(u.email or u.email_personal): u for u in db.scalars(select(Usuario))}
            admin = por_email.get("admin@empresa.com")
            if admin:
                admin.es_jefe = True
                laura.jefe_id = admin.id
                if "ana@empresa.com" in por_email:
                    por_email["ana@empresa.com"].jefe_id = admin.id
            for email in ("carlos@empresa.com", "maria@empresa.com"):
                if email in por_email:
                    por_email[email].jefe_id = laura.id
            db.commit()
            sincronizar_periodos(db, laura)

        # Médico de planta (idempotente)
        if not db.scalar(select(Usuario.id).where(Usuario.email == "medico@empresa.com")):
            medico = Usuario(numero_empleado="0700", nombre="Dra. Patricia Ruiz", email="medico@empresa.com",
                             password_hash=hash_password("Cambiar123"), rol="medico", fecha_ingreso=date(anio - 4, 9, 1),
                             puesto="Médico de planta", departamento="Servicio médico")
            admin = db.scalar(select(Usuario).where(Usuario.email == "admin@empresa.com"))
            medico.jefe_id = admin.id if admin else None
            db.add(medico)
            db.commit()
            sincronizar_periodos(db, medico)

        _asignar_sede(db, sede.id)
        print("Datos iniciales cargados.")
        print("  admin@empresa.com / Admin123")
        print("  laura@empresa.com (jefa de Carlos y María) / Cambiar123")
        print("  medico@empresa.com (médico de planta) / Cambiar123")
        print("  ana@empresa.com, carlos@empresa.com, maria@empresa.com / Cambiar123")
    finally:
        db.close()


def _asignar_sede(db, sede_id: int):
    """Catálogos y usuarios sin sede pasan a la sede inicial (idempotente)."""
    for modelo in (Turno, Grupo, Festivo, Usuario, RotacionTurnos):
        for obj in db.scalars(select(modelo).where(modelo.sede_id.is_(None))):
            obj.sede_id = sede_id
    db.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Datos iniciales de SIP-O")
    ap.add_argument("--solo-catalogos", action="store_true", help="No crear usuarios de ejemplo (producción)")
    main(solo_catalogos=ap.parse_args().solo_catalogos)
