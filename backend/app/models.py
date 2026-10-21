from datetime import date, datetime, time

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, Time, UniqueConstraint, false,
    func, true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Roles
ROL_ADMIN = "admin"
ROL_OFICINA = "oficina"
ROL_PLANTA = "planta"
ROL_MEDICO = "medico"  # médico de planta: registra consultas; para vacaciones se rige como oficinas
ROL_SUPERADMIN = "superadmin"  # todo lo del administrador + configuración de Microsoft y gestión de super admins
# "admin" se muestra como GH (Gestión Humana): administra solo su sede.
ROL_GERENCIA_GH = "gerencia_gh"  # Gerencia GH: mismos accesos que GH en las sedes que le asigne un super administrador
ROL_CASETA = "caseta"  # vigilancia: ve los permisos validados del día y registra retardos; vacaciones como oficinas
ROLES = (ROL_SUPERADMIN, ROL_GERENCIA_GH, ROL_ADMIN, ROL_OFICINA, ROL_PLANTA, ROL_MEDICO, ROL_CASETA)
ROLES_ADMIN = (ROL_ADMIN, ROL_GERENCIA_GH, ROL_SUPERADMIN)


def tiene_correo_corporativo(rol: str) -> bool:
    """Solo el personal de oficinas tiene correo corporativo (planta y caseta usan su correo personal)."""
    return rol not in (ROL_PLANTA, ROL_CASETA)


def correo_contacto(usuario) -> str | None:
    """Correo para avisos personales: el corporativo y, si no tiene, el personal."""
    return (usuario.email or usuario.email_personal) if usuario is not None else None


def es_admin(usuario) -> bool:
    """Administrador o super administrador."""
    return usuario is not None and usuario.rol in ROLES_ADMIN


ROLES_SIN_VACACIONES = (ROL_MEDICO, ROL_CASETA)  # solo usan su apartado (servicio médico / caseta)


def solicita_vacaciones(usuario) -> bool:
    """El médico de planta y caseta no piden vacaciones ni permisos en el sistema."""
    return usuario is not None and usuario.rol not in ROLES_SIN_VACACIONES


def es_medico(usuario) -> bool:
    """Médico de planta, usuario al que GH le permitió registrar consultas médicas o super administrador."""
    return usuario is not None and (usuario.rol in (ROL_MEDICO, ROL_SUPERADMIN) or bool(getattr(usuario, "puede_consultas", False)))

# Estados de solicitudes (vacaciones y permisos)
BORRADOR = "borrador"
SOLICITADO = "solicitado"
VALIDADO = "validado"
RECHAZADO = "rechazado"
CANCELADO = "cancelado"
ESTADOS = (BORRADOR, SOLICITADO, VALIDADO, RECHAZADO, CANCELADO)
ESTADOS_ACTIVOS = (BORRADOR, SOLICITADO, VALIDADO)  # consumen saldo

# Tipos de permiso
PERMISO_LLEGADA_TARDE = "llegada_tarde"
PERMISO_SALIDA_TEMPRANA = "salida_temprana"
PERMISO_SALIDA_INTERMEDIA = "salida_intermedia"
PERMISO_CONSULTA_MEDICA = "consulta_medica"  # histórico: ahora las consultas las registra el médico
PERMISO_HOME_OFFICE = "home_office"  # trabajo remoto por días (no es ausencia)
TIPOS_PERMISO = (
    PERMISO_LLEGADA_TARDE, PERMISO_SALIDA_TEMPRANA, PERMISO_SALIDA_INTERMEDIA, PERMISO_CONSULTA_MEDICA,
    PERMISO_HOME_OFFICE,
)

# Permisos que el empleado puede solicitar
TIPOS_PERMISO_SOLICITABLES = (PERMISO_LLEGADA_TARDE, PERMISO_SALIDA_TEMPRANA, PERMISO_SALIDA_INTERMEDIA,
                              PERMISO_HOME_OFFICE)

# Resultado de una consulta médica
RESULTADOS_CONSULTA = ("regresa_labores", "envia_casa", "referido")

# Cómo se considera el tiempo de un permiso en nómina
TIPOS_NOMINA = ("con_goce", "sin_goce", "reposicion")

# Ciclos de grupo
CICLO_SEMANAL = "semanal"     # días fijos de la semana (dias_semana)
CICLO_ROTATIVO = "rotativo"   # N días trabajo x M días descanso desde fecha_inicio_ciclo


ZONA_HORARIA_DEFECTO = "America/Mexico_City"


class Sede(Base):
    """Sede (ubicación de trabajo). Cada sede tiene su personal, catálogos, festivos, caseta y zona horaria."""
    __tablename__ = "sedes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    # "Ubicación del trabajo" (officeLocation) de Microsoft Entra ID con la que se asocia a los empleados
    ubicacion_microsoft: Mapped[str | None] = mapped_column(String(200), unique=True)
    zona_horaria: Mapped[str] = mapped_column(String(60), default=ZONA_HORARIA_DEFECTO)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    # Avisos a caseta de esta sede (el servidor de correo es común a todas)
    caseta_activo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    caseta_destinatarios: Mapped[str] = mapped_column(Text, default="")
    caseta_tipos: Mapped[str] = mapped_column(String(200), default="llegada_tarde,salida_temprana,salida_intermedia")
    # Correo con el que la sede envía sus avisos (la configura su GH). Vacío = usa la configuración general.
    correo_metodo: Mapped[str | None] = mapped_column(String(10))          # smtp | graph
    correo_remitente: Mapped[str | None] = mapped_column(String(200))
    correo_remitente_nombre: Mapped[str | None] = mapped_column(String(200))
    smtp_host: Mapped[str | None] = mapped_column(String(200))
    smtp_puerto: Mapped[int | None] = mapped_column(Integer)
    smtp_seguridad: Mapped[str | None] = mapped_column(String(12))
    smtp_usuario: Mapped[str | None] = mapped_column(String(200))
    smtp_password: Mapped[str | None] = mapped_column(Text)  # cifrada
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # ---- Política de vacaciones y permisos de la sede (la configura su GH) ----
    meses_vigencia: Mapped[int] = mapped_column(Integer, default=18, server_default="18")  # luego se pierden los días
    # True: se otorgan las horas de la tabla × 8 h y cada jornada las consume según sus horas (México);
    # False: cada día de la tabla es un día de la jornada del empleado (p. ej. 15 días hábiles para todos)
    equivalencia_horas: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    dias_anticipacion: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # para pedir vacaciones
    tipos_permiso: Mapped[str] = mapped_column(
        String(200), default="llegada_tarde,salida_temprana,salida_intermedia,home_office",
        server_default="llegada_tarde,salida_temprana,salida_intermedia,home_office")
    home_office_max_dias: Mapped[int] = mapped_column(Integer, default=31, server_default="31")
    modulo_consultas: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    modulo_cumpleanos: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Cuándo se generan los días: aniversario (al cumplir cada año), calendario (cada 1 de enero, el primero
    # proporcional a lo trabajado en el año de ingreso) o mensual (se acumulan mes a mes durante el año de servicio)
    generacion_dias: Mapped[str] = mapped_column(String(12), default="aniversario", server_default="aniversario")
    # Aprobación en dos niveles: primero el jefe y después GH
    aprobacion_gh_vacaciones: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    aprobacion_gh_permisos: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class TipoJornada(Base):
    """Tipo de jornada de una sede: horas por día, bloque mínimo de vacaciones y cómo se cuentan los días hábiles."""
    __tablename__ = "tipos_jornada"
    __table_args__ = (UniqueConstraint("sede_id", "nombre", name="uq_jornadas_sede_nombre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(80))
    horas_dia: Mapped[int] = mapped_column(Integer, default=8)
    bloque_minimo: Mapped[int] = mapped_column(Integer, default=6)  # días seguidos que se toman al menos una vez
    # False: lunes a viernes; True: según el ciclo del grupo del empleado (p. ej. 4×4)
    usa_ciclo_grupo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Cómo se lleva el saldo: "horas" (tabla × 8 h y cada día descuenta las horas de la jornada), "dias" (cada día de
    # la tabla es un día de esta jornada) o vacío = lo que diga la política de la sede
    descuento: Mapped[str | None] = mapped_column(String(10))
    # Vacaciones por horas (p. ej. 4 h de una jornada de 12 h), con un mínimo de horas por solicitud
    por_horas: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    minimo_horas: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class AdminSede(Base):
    """Sedes adicionales que puede administrar un administrador (además de la suya)."""
    __tablename__ = "admin_sedes"

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id", ondelete="CASCADE"), primary_key=True)


class Turno(Base):
    __tablename__ = "turnos"
    __table_args__ = (UniqueConstraint("sede_id", "nombre", name="uq_turnos_sede_nombre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(80))
    hora_entrada: Mapped[time] = mapped_column(Time)
    hora_salida: Mapped[time] = mapped_column(Time)
    horas_jornada: Mapped[int] = mapped_column(Integer, default=12)
    descripcion: Mapped[str | None] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    sede: Mapped[Sede | None] = relationship()
    # Horario distinto por día de la semana (si no hay, aplica el horario general)
    dias: Mapped[list["TurnoDia"]] = relationship(cascade="all, delete-orphan", order_by="TurnoDia.dia")
    # Horarios especiales por temporada o semanas alternas (p. ej. "Short Friday"); tienen prioridad
    especiales: Mapped[list["HorarioEspecial"]] = relationship(cascade="all, delete-orphan",
                                                                order_by="HorarioEspecial.fecha_inicio")

    @property
    def sede_nombre(self) -> str | None:
        return self.sede.nombre if self.sede else None


class TurnoDia(Base):
    """Horario de un turno para un día de la semana (0 = lunes ... 6 = domingo)."""
    __tablename__ = "turnos_dias"
    __table_args__ = (UniqueConstraint("turno_id", "dia", name="uq_turnos_dias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    turno_id: Mapped[int] = mapped_column(ForeignKey("turnos.id", ondelete="CASCADE"), index=True)
    dia: Mapped[int] = mapped_column(Integer)
    hora_entrada: Mapped[time] = mapped_column(Time)
    hora_salida: Mapped[time] = mapped_column(Time)


class HorarioEspecial(Base):
    """Horario que reemplaza al normal en ciertos días de un rango de fechas, opcionalmente cada N semanas
    (p. ej. "Short Friday": viernes de 8:30 a 15:00 cada 2 semanas durante el verano)."""
    __tablename__ = "horarios_especiales"

    id: Mapped[int] = mapped_column(primary_key=True)
    turno_id: Mapped[int] = mapped_column(ForeignKey("turnos.id", ondelete="CASCADE"), index=True)
    nombre: Mapped[str] = mapped_column(String(80))
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date | None] = mapped_column(Date)  # vacío = sin fecha de fin
    dias: Mapped[str] = mapped_column(String(20), default="4")  # días de la semana: "4" = viernes
    cada_semanas: Mapped[int] = mapped_column(Integer, default=1)  # 1 = todas las semanas, 2 = una sí y una no
    hora_entrada: Mapped[time] = mapped_column(Time)
    hora_salida: Mapped[time] = mapped_column(Time)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Grupo(Base):
    __tablename__ = "grupos"
    __table_args__ = (UniqueConstraint("sede_id", "nombre", name="uq_grupos_sede_nombre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(80))
    descripcion: Mapped[str | None] = mapped_column(String(255))
    tipo_ciclo: Mapped[str] = mapped_column(String(20), default=CICLO_ROTATIVO)
    # semanal: "0,1,2,3" (0 = lunes ... 6 = domingo)
    dias_semana: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4")
    # rotativo
    dias_trabajo: Mapped[int] = mapped_column(Integer, default=4)
    dias_descanso: Mapped[int] = mapped_column(Integer, default=4)
    fecha_inicio_ciclo: Mapped[date | None] = mapped_column(Date)
    color: Mapped[str] = mapped_column(String(9), default="#1976d2")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Rotación de turnos: si participa y con qué turno empieza el primer periodo
    en_rotacion: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    rotacion_turno_inicial_id: Mapped[int | None] = mapped_column(ForeignKey("turnos.id", ondelete="SET NULL"))

    miembros: Mapped[list["Usuario"]] = relationship(back_populates="grupo")
    sede: Mapped[Sede | None] = relationship()

    @property
    def sede_nombre(self) -> str | None:
        return self.sede.nombre if self.sede else None


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero_empleado: Mapped[str] = mapped_column(String(30), unique=True)
    nombre: Mapped[str] = mapped_column(String(150))
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), index=True)
    tipo_jornada_id: Mapped[int | None] = mapped_column(ForeignKey("tipos_jornada.id", ondelete="SET NULL"))
    # Correo corporativo (solo personal de oficinas: oficina, admin, super admin y médico); planta no tiene
    email: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    email_personal: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(20), default=ROL_OFICINA)
    fecha_ingreso: Mapped[date] = mapped_column(Date)
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date)  # en el calendario solo se muestra día y mes
    puesto: Mapped[str | None] = mapped_column(String(120))
    departamento: Mapped[str | None] = mapped_column(String(120))
    turno_id: Mapped[int | None] = mapped_column(ForeignKey("turnos.id", ondelete="SET NULL"))
    grupo_id: Mapped[int | None] = mapped_column(ForeignKey("grupos.id", ondelete="SET NULL"))
    # Jefe directo (aprobador por defecto) y si este usuario puede aprobar solicitudes de su equipo
    jefe_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    es_jefe: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Además del médico de planta, GH puede permitir a otros usuarios registrar consultas (e incapacidades)
    puede_consultas: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Datos de contacto
    direccion: Mapped[str | None] = mapped_column(String(255))
    telefono: Mapped[str | None] = mapped_column(String(30))
    contacto_nombre: Mapped[str | None] = mapped_column(String(150))      # contacto de emergencia
    contacto_telefono: Mapped[str | None] = mapped_column(String(30))
    # Vínculo con Microsoft Entra ID y foto de perfil (obtenida de Microsoft Graph)
    microsoft_oid: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    foto: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    foto_tipo: Mapped[str | None] = mapped_column(String(40))
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actualizado: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime)
    # Última vez que el usuario confirmó o actualizó sus datos personales (cada 6 meses se le vuelve a pedir)
    datos_confirmados: Mapped[datetime | None] = mapped_column(DateTime)
    # Contraseña temporal (6 dígitos) que se debe cambiar en el primer inicio de sesión
    debe_cambiar_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    password_temporal_expira: Mapped[datetime | None] = mapped_column(DateTime)
    # Protección contra intentos de adivinar la contraseña
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime)

    turno: Mapped[Turno | None] = relationship()
    grupo: Mapped[Grupo | None] = relationship(back_populates="miembros")
    sede: Mapped[Sede | None] = relationship()
    tipo_jornada: Mapped[TipoJornada | None] = relationship()
    jefe: Mapped["Usuario | None"] = relationship(remote_side="Usuario.id", foreign_keys=[jefe_id])
    periodos: Mapped[list["PeriodoVacaciones"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan", order_by="PeriodoVacaciones.numero"
    )


class ReglaAntiguedad(Base):
    """Tabla de días de vacaciones por años de servicio de una sede (editable por su administrador).

    Una sede sin filas propias usa la tabla de la sede principal (México)."""
    __tablename__ = "reglas_antiguedad"

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), index=True)
    anios_desde: Mapped[int] = mapped_column(Integer)
    anios_hasta: Mapped[int] = mapped_column(Integer)
    dias: Mapped[int] = mapped_column(Integer)


class Festivo(Base):
    __tablename__ = "festivos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), index=True)  # cada sede tiene sus festivos
    fecha: Mapped[date] = mapped_column(Date, index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    # "todos" | "oficina" | "planta"
    aplica_a: Mapped[str] = mapped_column(String(20), default="todos")

    sede: Mapped[Sede | None] = relationship()

    @property
    def sede_nombre(self) -> str | None:
        return self.sede.nombre if self.sede else None


class PeriodoVacaciones(Base):
    __tablename__ = "periodos_vacaciones"
    __table_args__ = (UniqueConstraint("usuario_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    numero: Mapped[int] = mapped_column(Integer)  # año de servicio
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_vencimiento: Mapped[date] = mapped_column(Date)
    dias_ley: Mapped[int] = mapped_column(Integer)          # días de 8 h según tabla
    horas_otorgadas: Mapped[float] = mapped_column(Float)   # dias_ley * 8
    horas_por_dia: Mapped[int] = mapped_column(Integer)     # 8 oficina / 12 planta
    ajuste_horas: Mapped[float] = mapped_column(Float, default=0)
    nota_ajuste: Mapped[str | None] = mapped_column(String(255))

    usuario: Mapped[Usuario] = relationship(back_populates="periodos")

    @property
    def nombre(self) -> str:
        return f"Periodo {self.fecha_inicio.year}"


class SolicitudVacaciones(Base):
    __tablename__ = "solicitudes_vacaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("periodos_vacaciones.id", ondelete="CASCADE"))
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date] = mapped_column(Date)
    dias_habiles: Mapped[int] = mapped_column(Integer)
    horas: Mapped[float] = mapped_column(Float)
    por_horas: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # parte de una jornada
    planeada: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())   # la programó GH
    estado: Mapped[str] = mapped_column(String(20), default=BORRADOR, index=True)
    comentario: Mapped[str | None] = mapped_column(Text)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text)
    firma: Mapped[str | None] = mapped_column(Text)  # imagen PNG en data URL
    aprobador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    # Dos niveles: el jefe aprueba (queda pendiente de GH) y GH valida
    aprobado_jefe_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha_aprobado_jefe: Mapped[datetime | None] = mapped_column(DateTime)
    revisado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha_revision: Mapped[datetime | None] = mapped_column(DateTime)
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actualizado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])
    periodo: Mapped[PeriodoVacaciones] = relationship()
    aprobador: Mapped[Usuario | None] = relationship(foreign_keys=[aprobador_id])
    revisado_por: Mapped[Usuario | None] = relationship(foreign_keys=[revisado_por_id])
    aprobado_jefe: Mapped[Usuario | None] = relationship(foreign_keys=[aprobado_jefe_id])


class TipoPermisoSede(Base):
    """Tipo de permiso de una sede (los 4 base y los que agregue GH), con su límite por mes, año o sin límite."""
    __tablename__ = "tipos_permiso"
    __table_args__ = (UniqueConstraint("sede_id", "clave", name="uq_tipos_permiso_sede_clave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id", ondelete="CASCADE"), index=True)
    clave: Mapped[str] = mapped_column(String(30))
    nombre: Mapped[str] = mapped_column(String(80))
    modalidad: Mapped[str] = mapped_column(String(10), default="horas")  # horas (un día con horario) | dias (rango)
    pide_nomina: Mapped[bool] = mapped_column(Boolean, default=True)    # con goce / sin goce / reposición
    limite_cantidad: Mapped[float | None] = mapped_column(Float)        # vacío = sin límite
    limite_unidad: Mapped[str] = mapped_column(String(10), default="dias")   # dias | horas
    limite_periodo: Mapped[str | None] = mapped_column(String(10))      # mes | anio | vacío = en total
    max_dias_solicitud: Mapped[int | None] = mapped_column(Integer)     # por días: máximo de días naturales por solicitud
    color: Mapped[str] = mapped_column(String(9), default="#6d4c41")
    base: Mapped[bool] = mapped_column(Boolean, default=False)          # los 4 tipos originales: no se borran
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    orden: Mapped[int] = mapped_column(Integer, default=100)


class Permiso(Base):
    """Permisos de llegada tarde, salida temprana, salida intermedia y consulta con el médico de planta."""
    __tablename__ = "permisos"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(30))
    fecha: Mapped[date] = mapped_column(Date, index=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date)  # home office: último día del rango
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fin: Mapped[time] = mapped_column(Time)
    horas: Mapped[float] = mapped_column(Float)
    motivo: Mapped[str | None] = mapped_column(Text)
    observaciones: Mapped[str | None] = mapped_column(Text)  # p. ej. notas del médico de planta
    departamento: Mapped[str | None] = mapped_column(String(120))
    tipo_nomina: Mapped[str | None] = mapped_column(String(30))  # cómo se considera el tiempo en nómina
    firma: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default=BORRADOR, index=True)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text)
    aprobador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    # Dos niveles: el jefe aprueba (queda pendiente de GH) y GH valida
    aprobado_jefe_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha_aprobado_jefe: Mapped[datetime | None] = mapped_column(DateTime)
    revisado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha_revision: Mapped[datetime | None] = mapped_column(DateTime)
    # Retardo registrado por caseta (el empleado no lo solicitó ni lo firmó)
    registrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])
    registrado_por: Mapped[Usuario | None] = relationship(foreign_keys=[registrado_por_id])
    aprobador: Mapped[Usuario | None] = relationship(foreign_keys=[aprobador_id])
    revisado_por: Mapped[Usuario | None] = relationship(foreign_keys=[revisado_por_id])
    aprobado_jefe: Mapped[Usuario | None] = relationship(foreign_keys=[aprobado_jefe_id])


class Sesion(Base):
    """Sesión del navegador. La cookie guarda un token aleatorio; aquí solo su hash SHA-256."""
    __tablename__ = "sesiones"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(token)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    metodo: Mapped[str] = mapped_column(String(20))  # password | microsoft
    csrf: Mapped[str] = mapped_column(String(64))
    creado: Mapped[datetime] = mapped_column(DateTime)
    expira: Mapped[datetime] = mapped_column(DateTime, index=True)
    ultimo_uso: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    usuario: Mapped[Usuario] = relationship()


class FlujoOAuth(Base):
    """Estado temporal del inicio de sesión con Microsoft (state, nonce y PKCE), de un solo uso."""
    __tablename__ = "flujos_oauth"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    siguiente: Mapped[str] = mapped_column(String(255), default="/")
    creado: Mapped[datetime] = mapped_column(DateTime, index=True)


class Auditoria(Base):
    """Bitácora de accesos y cambios relevantes (sin tokens ni secretos)."""
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    evento: Mapped[str] = mapped_column(String(50), index=True)
    detalle: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))


class Bitacora(Base):
    """Bitácora de cambios hechos por los usuarios (configuración y vacaciones). La llena app/bitacora.py."""
    __tablename__ = "bitacora"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, index=True)
    seccion: Mapped[str] = mapped_column(String(20), index=True)   # configuracion | vacaciones
    accion: Mapped[str] = mapped_column(String(20))                # crear | editar | estado | eliminar
    entidad: Mapped[str] = mapped_column(String(60))               # Turno, Festivo, Solicitud de vacaciones...
    entidad_id: Mapped[str | None] = mapped_column(String(40))
    descripcion: Mapped[str] = mapped_column(String(255), default="")
    # Sin llave foránea: la historia se conserva aunque se elimine la sede o el usuario
    sede_id: Mapped[int | None] = mapped_column(Integer, index=True)
    sede_nombre: Mapped[str | None] = mapped_column(String(120))
    actor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    actor_nombre: Mapped[str | None] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(String(64))
    cambios: Mapped[str] = mapped_column(Text, default="[]")       # JSON: [{campo, antes, despues}]


class ListaSharePoint(Base):
    """Lista de SharePoint a la que se envían las solicitudes de una sede (una para vacaciones y otra para permisos)."""
    __tablename__ = "sharepoint_listas"
    __table_args__ = (UniqueConstraint("sede_id", "tipo", name="uq_sharepoint_sede_tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # vacaciones | permisos
    url: Mapped[str] = mapped_column(Text)
    sitio_id: Mapped[str] = mapped_column(String(300))
    sitio_nombre: Mapped[str | None] = mapped_column(String(200))
    lista_id: Mapped[str] = mapped_column(String(80))
    lista_nombre: Mapped[str | None] = mapped_column(String(200))
    columnas: Mapped[str] = mapped_column(Text, default="[]")  # columnas editables leídas de la lista (JSON)
    mapeo: Mapped[str] = mapped_column(Text, default="{}")     # {columna de la lista: dato de SIP-O}
    valores: Mapped[str] = mapped_column(Text, default="{}")   # {columna: {valor de SIP-O: opción de la lista}}
    activo: Mapped[bool] = mapped_column(Boolean, default=False)
    actualizado: Mapped[datetime | None] = mapped_column(DateTime)
    actualizado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    # Aprobación en Teams: un flujo de Power Automate pide la aprobación al jefe y escribe la decisión en la lista;
    # SIP-O la lee y la aplica. Columnas de la lista que escribe el flujo (SIP-O no las llena):
    aprobacion_teams: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    col_decision: Mapped[str | None] = mapped_column(String(120))    # "Approve" / "Reject" (resultado del flujo)
    val_aprobado: Mapped[str | None] = mapped_column(String(120))
    val_rechazado: Mapped[str | None] = mapped_column(String(120))
    col_comentario: Mapped[str | None] = mapped_column(String(120))  # comentarios del jefe
    col_respondio: Mapped[str | None] = mapped_column(String(120))   # correo de quien respondió
    cuenta_flujo: Mapped[str | None] = mapped_column(String(200))    # cuenta con la que corre el flujo (verificación)

    sede: Mapped[Sede] = relationship()


class EnvioSharePoint(Base):
    """Cola de envío a SharePoint: un renglón por solicitud y lista, con el id del elemento creado en la lista."""
    __tablename__ = "sharepoint_envios"
    __table_args__ = (UniqueConstraint("lista_id", "registro_id", name="uq_sharepoint_envio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lista_id: Mapped[int] = mapped_column(ForeignKey("sharepoint_listas.id", ondelete="CASCADE"), index=True)
    registro_id: Mapped[int] = mapped_column(Integer, index=True)  # id de la solicitud de vacaciones o del permiso
    item_id: Mapped[str | None] = mapped_column(String(40))
    estado: Mapped[str] = mapped_column(String(12), default="pendiente", index=True)  # pendiente | enviado | error
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    eliminado: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    actualizado: Mapped[datetime | None] = mapped_column(DateTime)
    enviado: Mapped[datetime | None] = mapped_column(DateTime)
    decision_nota: Mapped[str | None] = mapped_column(Text)  # p. ej. por qué se ignoró una decisión de Teams

    lista: Mapped[ListaSharePoint] = relationship()


class CanalAprobacion(Base):
    """Aprobación en Teams por un flujo de Power Automate con disparador HTTP (una configuración por sede)."""
    __tablename__ = "aprobacion_flujo"

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id", ondelete="CASCADE"), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=False)
    tipos: Mapped[str] = mapped_column(String(40), default="vacaciones,permisos")
    flujo_url: Mapped[str | None] = mapped_column(Text)  # cifrada: quien la tenga puede iniciar aprobaciones
    lista_url: Mapped[str | None] = mapped_column(Text)  # lista "Decisiones SIP-O" donde el flujo deja la respuesta
    sitio_id: Mapped[str | None] = mapped_column(String(300))
    lista_id: Mapped[str | None] = mapped_column(String(80))
    lista_nombre: Mapped[str | None] = mapped_column(String(200))
    cuenta_flujo: Mapped[str | None] = mapped_column(String(200))
    actualizado: Mapped[datetime | None] = mapped_column(DateTime)
    actualizado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))

    sede: Mapped[Sede] = relationship()


class SolicitudAprobacion(Base):
    """Cada solicitud enviada al flujo de aprobación (con su token de un solo uso)."""
    __tablename__ = "aprobacion_flujo_envios"
    __table_args__ = (UniqueConstraint("tipo", "registro_id", name="uq_aprobacion_flujo_registro"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int | None] = mapped_column(Integer, index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # vacaciones | permisos
    registro_id: Mapped[int] = mapped_column(Integer)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    estado: Mapped[str] = mapped_column(String(12), default="pendiente", index=True)  # pendiente|enviada|resuelta|cerrada|error
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    decision_nota: Mapped[str | None] = mapped_column(Text)
    creado: Mapped[datetime | None] = mapped_column(DateTime)
    enviado: Mapped[datetime | None] = mapped_column(DateTime)
    resuelto: Mapped[datetime | None] = mapped_column(DateTime)
    actualizado: Mapped[datetime | None] = mapped_column(DateTime)


class ConfiguracionApp(Base):
    """Valores de configuración editables desde la pantalla de Configuración (tienen prioridad sobre .env).

    Los secretos se guardan cifrados (Fernet, llave derivada de SECRET_KEY) y nunca se devuelven al navegador.
    """
    __tablename__ = "configuracion"

    clave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[str | None] = mapped_column(Text)
    cifrado: Mapped[bool] = mapped_column(Boolean, default=False)
    actualizado: Mapped[datetime] = mapped_column(DateTime)
    actualizado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))


class ConsultaMedica(Base):
    """Consulta registrada por el médico de planta. Datos clínicos: solo médico y paciente."""
    __tablename__ = "consultas_medicas"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    medico_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha: Mapped[date] = mapped_column(Date, index=True)
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fin: Mapped[time | None] = mapped_column(Time)
    sintomas: Mapped[str] = mapped_column(Text)
    diagnostico: Mapped[str | None] = mapped_column(Text)
    indicaciones: Mapped[str | None] = mapped_column(Text)
    resultado: Mapped[str] = mapped_column(String(30), default="regresa_labores")
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actualizado: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    paciente: Mapped[Usuario] = relationship(foreign_keys=[paciente_id])
    medico: Mapped[Usuario | None] = relationship(foreign_keys=[medico_id])
    medicamentos: Mapped[list["MedicamentoRecetado"]] = relationship(
        back_populates="consulta", cascade="all, delete-orphan", order_by="MedicamentoRecetado.id")
    incapacidad: Mapped["Incapacidad | None"] = relationship(back_populates="consulta", cascade="all, delete-orphan",
                                                             uselist=False)


TIPOS_INCAPACIDAD = ("enfermedad_general", "riesgo_trabajo", "maternidad", "otro")


class Incapacidad(Base):
    """Incapacidad generada en una consulta médica; la valida el jefe del empleado y se notifica a GH.

    El jefe y GH ven fechas, días, tipo y folio, nunca la información clínica de la consulta."""
    __tablename__ = "incapacidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    consulta_id: Mapped[int] = mapped_column(ForeignKey("consultas_medicas.id", ondelete="CASCADE"), unique=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    medico_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    aprobador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    fecha_inicio: Mapped[date] = mapped_column(Date, index=True)
    fecha_fin: Mapped[date] = mapped_column(Date)
    dias: Mapped[int] = mapped_column(Integer, default=1)                 # días naturales
    tipo: Mapped[str] = mapped_column(String(30), default="enfermedad_general")
    folio: Mapped[str | None] = mapped_column(String(40))                  # p. ej. folio del IMSS
    observaciones: Mapped[str | None] = mapped_column(String(500))         # visible para el jefe y GH
    estado: Mapped[str] = mapped_column(String(20), default=SOLICITADO, index=True)
    revisado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha_revision: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text)
    # Si el jefe ajusta los días al validarla, se guardan las fechas que había registrado el servicio médico
    fecha_inicio_original: Mapped[date | None] = mapped_column(Date)
    fecha_fin_original: Mapped[date | None] = mapped_column(Date)
    nota_revision: Mapped[str | None] = mapped_column(String(500))
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    consulta: Mapped["ConsultaMedica"] = relationship(back_populates="incapacidad")
    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])
    medico: Mapped[Usuario | None] = relationship(foreign_keys=[medico_id])
    aprobador: Mapped[Usuario | None] = relationship(foreign_keys=[aprobador_id])
    revisado_por: Mapped[Usuario | None] = relationship(foreign_keys=[revisado_por_id])


class MedicamentoRecetado(Base):
    __tablename__ = "medicamentos_recetados"

    id: Mapped[int] = mapped_column(primary_key=True)
    consulta_id: Mapped[int] = mapped_column(ForeignKey("consultas_medicas.id", ondelete="CASCADE"), index=True)
    nombre: Mapped[str] = mapped_column(String(150))
    dosis: Mapped[str | None] = mapped_column(String(100))
    frecuencia: Mapped[str | None] = mapped_column(String(100))
    duracion: Mapped[str | None] = mapped_column(String(100))

    consulta: Mapped[ConsultaMedica] = relationship(back_populates="medicamentos")


class NotificacionCorreo(Base):
    """Bitácora de correos enviados (p. ej. avisos a caseta de permisos autorizados)."""
    __tablename__ = "notificaciones_correo"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, index=True)
    evento: Mapped[str] = mapped_column(String(40))  # permiso_autorizado | permiso_cancelado | prueba
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), index=True)
    permiso_id: Mapped[int | None] = mapped_column(ForeignKey("permisos.id", ondelete="SET NULL"), index=True)
    incapacidad_id: Mapped[int | None] = mapped_column(ForeignKey("incapacidades.id", ondelete="SET NULL"), index=True)
    destinatarios: Mapped[str] = mapped_column(Text)
    asunto: Mapped[str] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente | enviado | error
    error: Mapped[str | None] = mapped_column(Text)
    intentos: Mapped[int] = mapped_column(Integer, default=0)

    permiso: Mapped["Permiso | None"] = relationship()


class RotacionTurnos(Base):
    """Configuración de la rotación de turnos entre grupos (una por sede)."""
    __tablename__ = "rotacion_turnos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), index=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_inicio: Mapped[date | None] = mapped_column(Date)       # inicio del primer periodo (día de cambio)
    semanas: Mapped[int] = mapped_column(Integer, default=1)      # cada cuántas semanas cambian de turno
    turnos_orden: Mapped[str] = mapped_column(String(200), default="")  # ids de turnos en orden de rotación: "2,3"
    turno_unico_id: Mapped[int | None] = mapped_column(ForeignKey("turnos.id", ondelete="SET NULL"))
    aviso_activo: Mapped[bool] = mapped_column(Boolean, default=False)  # correo semanal (viernes)
    aviso_hora: Mapped[int] = mapped_column(Integer, default=12)
    ultimo_aviso: Mapped[date | None] = mapped_column(Date)
    ultima_sincronizacion: Mapped[date | None] = mapped_column(Date)
    actualizado: Mapped[datetime | None] = mapped_column(DateTime)

    turno_unico: Mapped[Turno | None] = relationship()
