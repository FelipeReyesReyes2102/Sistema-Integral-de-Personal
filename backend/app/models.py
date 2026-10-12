from datetime import date, datetime, time

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, Time, UniqueConstraint, false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Roles
ROL_ADMIN = "admin"
ROL_OFICINA = "oficina"
ROL_PLANTA = "planta"
ROL_MEDICO = "medico"  # médico de planta: registra consultas; para vacaciones se rige como oficinas
ROL_SUPERADMIN = "superadmin"  # todo lo del administrador + configuración de Microsoft y gestión de super admins
ROLES = (ROL_SUPERADMIN, ROL_ADMIN, ROL_OFICINA, ROL_PLANTA, ROL_MEDICO)
ROLES_ADMIN = (ROL_ADMIN, ROL_SUPERADMIN)


def tiene_correo_corporativo(rol: str) -> bool:
    """Solo el personal de oficinas tiene correo corporativo."""
    return rol != ROL_PLANTA


def correo_contacto(usuario) -> str | None:
    """Correo para avisos personales: el corporativo y, si no tiene, el personal."""
    return (usuario.email or usuario.email_personal) if usuario is not None else None


def es_admin(usuario) -> bool:
    """Administrador o super administrador."""
    return usuario is not None and usuario.rol in ROLES_ADMIN

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


class Turno(Base):
    __tablename__ = "turnos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
    hora_entrada: Mapped[time] = mapped_column(Time)
    hora_salida: Mapped[time] = mapped_column(Time)
    horas_jornada: Mapped[int] = mapped_column(Integer, default=12)
    descripcion: Mapped[str | None] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Grupo(Base):
    __tablename__ = "grupos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
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


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero_empleado: Mapped[str] = mapped_column(String(30), unique=True)
    nombre: Mapped[str] = mapped_column(String(150))
    # Correo corporativo (solo personal de oficinas: oficina, admin, super admin y médico); planta no tiene
    email: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    email_personal: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(20), default=ROL_OFICINA)
    fecha_ingreso: Mapped[date] = mapped_column(Date)
    puesto: Mapped[str | None] = mapped_column(String(120))
    departamento: Mapped[str | None] = mapped_column(String(120))
    turno_id: Mapped[int | None] = mapped_column(ForeignKey("turnos.id", ondelete="SET NULL"))
    grupo_id: Mapped[int | None] = mapped_column(ForeignKey("grupos.id", ondelete="SET NULL"))
    # Jefe directo (aprobador por defecto) y si este usuario puede aprobar solicitudes de su equipo
    jefe_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    es_jefe: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Vínculo con Microsoft Entra ID y foto de perfil (obtenida de Microsoft Graph)
    microsoft_oid: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    foto: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    foto_tipo: Mapped[str | None] = mapped_column(String(40))
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actualizado: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime)

    turno: Mapped[Turno | None] = relationship()
    grupo: Mapped[Grupo | None] = relationship(back_populates="miembros")
    jefe: Mapped["Usuario | None"] = relationship(remote_side="Usuario.id", foreign_keys=[jefe_id])
    periodos: Mapped[list["PeriodoVacaciones"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan", order_by="PeriodoVacaciones.numero"
    )


class ReglaAntiguedad(Base):
    """Tabla de días de vacaciones por años de servicio (editable por el administrador)."""
    __tablename__ = "reglas_antiguedad"

    id: Mapped[int] = mapped_column(primary_key=True)
    anios_desde: Mapped[int] = mapped_column(Integer)
    anios_hasta: Mapped[int] = mapped_column(Integer)
    dias: Mapped[int] = mapped_column(Integer)


class Festivo(Base):
    __tablename__ = "festivos"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    # "todos" | "oficina" | "planta"
    aplica_a: Mapped[str] = mapped_column(String(20), default="todos")


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
    estado: Mapped[str] = mapped_column(String(20), default=BORRADOR, index=True)
    comentario: Mapped[str | None] = mapped_column(Text)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text)
    firma: Mapped[str | None] = mapped_column(Text)  # imagen PNG en data URL
    aprobador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    revisado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha_revision: Mapped[datetime | None] = mapped_column(DateTime)
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actualizado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])
    periodo: Mapped[PeriodoVacaciones] = relationship()
    aprobador: Mapped[Usuario | None] = relationship(foreign_keys=[aprobador_id])
    revisado_por: Mapped[Usuario | None] = relationship(foreign_keys=[revisado_por_id])


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
    revisado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    fecha_revision: Mapped[datetime | None] = mapped_column(DateTime)
    creado: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])
    aprobador: Mapped[Usuario | None] = relationship(foreign_keys=[aprobador_id])
    revisado_por: Mapped[Usuario | None] = relationship(foreign_keys=[revisado_por_id])


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
    permiso_id: Mapped[int | None] = mapped_column(ForeignKey("permisos.id", ondelete="SET NULL"), index=True)
    destinatarios: Mapped[str] = mapped_column(Text)
    asunto: Mapped[str] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente | enviado | error
    error: Mapped[str | None] = mapped_column(Text)
    intentos: Mapped[int] = mapped_column(Integer, default=0)

    permiso: Mapped["Permiso | None"] = relationship()


class RotacionTurnos(Base):
    """Configuración única (id=1) de la rotación de turnos entre grupos."""
    __tablename__ = "rotacion_turnos"

    id: Mapped[int] = mapped_column(primary_key=True)
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
