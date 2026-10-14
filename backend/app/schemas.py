from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Rol = Literal["superadmin", "gerencia_gh", "admin", "oficina", "planta", "medico"]
TipoPermiso = Literal["llegada_tarde", "salida_temprana", "salida_intermedia", "consulta_medica", "home_office"]
TipoNomina = Literal["con_goce", "sin_goce", "reposicion"]
Firma = Annotated[str, Field(max_length=400_000, pattern=r"^data:image/png;base64,[A-Za-z0-9+/=]+$")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class LoginIn(BaseModel):
    """Se puede entrar con el correo o con el número de nómina (`usuario`)."""
    usuario: str | None = None
    email: str | None = None  # compatibilidad: antes solo se aceptaba el correo
    password: str


class CambioPassword(BaseModel):
    actual: str
    nueva: str = Field(min_length=8, max_length=128)

    @field_validator("nueva")
    @classmethod
    def _segura(cls, v: str) -> str:
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("La contraseña debe tener al menos 8 caracteres e incluir letras y números")
        return v


# ---------- Turnos / Grupos ----------
class TurnoIn(BaseModel):
    nombre: str
    hora_entrada: time
    hora_salida: time
    horas_jornada: int = Field(12, ge=1, le=24)
    descripcion: str | None = None
    activo: bool = True


class TurnoOut(TurnoIn, ORM):
    id: int
    sede_id: int | None = None
    sede_nombre: str | None = None


class GrupoIn(BaseModel):
    nombre: str
    descripcion: str | None = None
    tipo_ciclo: Literal["semanal", "rotativo"] = "rotativo"
    dias_semana: str = "0,1,2,3,4"
    dias_trabajo: int = Field(4, ge=1, le=30)
    dias_descanso: int = Field(4, ge=0, le=30)
    fecha_inicio_ciclo: date | None = None
    color: str = "#1976d2"
    activo: bool = True


class GrupoOut(GrupoIn, ORM):
    id: int
    sede_id: int | None = None
    sede_nombre: str | None = None
    total_miembros: int = 0


class AsignarMiembros(BaseModel):
    usuario_ids: list[int]
    turno_id: int | None = None  # opcional: asigna también el turno a todos


# ---------- Usuarios ----------
class UsuarioBase(BaseModel):
    numero_empleado: str
    nombre: str
    sede_id: int | None = None          # por defecto la sede activa del administrador
    tipo_jornada_id: int | None = None  # por defecto la jornada de su sede según su tipo de usuario
    email: str | None = None            # correo corporativo (solo oficinas)
    email_personal: str | None = None
    rol: Rol = "oficina"
    fecha_ingreso: date
    fecha_nacimiento: date | None = None
    puesto: str | None = None
    departamento: str | None = None
    turno_id: int | None = None
    grupo_id: int | None = None
    jefe_id: int | None = None
    es_jefe: bool = False
    activo: bool = True


class UsuarioIn(UsuarioBase):
    # Opcional: sin contraseña el usuario solo podrá entrar con Microsoft
    password: str | None = Field(None, min_length=6)
    microsoft_oid: str | None = Field(None, max_length=64)
    foto: Annotated[str, Field(max_length=700_000, pattern=r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=]+$")] | None = None
    quitar_foto: bool = False
    # Opcional: días de vacaciones disponibles hoy. Se llenan primero en el periodo actual (hasta sus días de ley)
    # y el resto en el periodo anterior.
    dias_disponibles: float | None = Field(None, ge=0, le=400)
    # Solo super administrador: sedes adicionales que administra un administrador
    sedes_admin: list[int] | None = None


class UsuarioOut(UsuarioBase, ORM):
    id: int
    sede_nombre: str | None = None
    sedes_admin: list[int] = []
    tipo_jornada_nombre: str | None = None
    turno_nombre: str | None = None
    grupo_nombre: str | None = None
    jefe_nombre: str | None = None
    antiguedad_anios: int = 0
    total_a_cargo: int = 0
    tiene_foto: bool = False
    microsoft_vinculado: bool = False
    ultimo_acceso: datetime | None = None
    debe_cambiar_password: bool = False
    bloqueado: bool = False
    # Solo se llena al crear el usuario o al restablecer su contraseña: se muestra una sola vez
    password_temporal: str | None = None
    password_temporal_expira: datetime | None = None


class MeOut(UsuarioOut):
    """Respuesta de /api/auth/me: solo información segura del usuario autenticado."""
    authenticated: bool = True
    display_name: str
    role: str
    auth_method: str | None = None
    permissions: list[str] = []
    puede_usar_password: bool = True
    sedes: list[dict] = []   # sedes que puede consultar (selector del menú)


class JefeOut(ORM):
    id: int
    nombre: str
    sede_id: int | None = None
    email: str | None = None
    puesto: str | None
    departamento: str | None
    rol: str


class MiembroEquipoOut(BaseModel):
    usuario: UsuarioOut
    periodo_actual: str | None = None
    vence: date | None = None
    dias_total: float = 0
    dias_tomados: float = 0       # validado
    dias_solicitados: float = 0   # solicitado + borrador
    dias_restantes: float = 0
    dias_restantes_vigentes: float = 0  # suma de todos los periodos vigentes
    dias_perdidos: float = 0            # días que perdió por periodos vencidos
    dias_por_vencer: float = 0          # saldo de un periodo anterior que vence pronto
    fecha_por_vencer: date | None = None
    pendientes_por_aprobar: int = 0
    proximas_vacaciones: date | None = None
    de_vacaciones_hoy: bool = False


class EmpleadoMicrosoftOut(BaseModel):
    """Datos de un empleado obtenidos de Microsoft Graph para prellenar el alta."""
    oid: str
    nombre: str | None = None
    email: str
    puesto: str | None = None
    departamento: str | None = None
    numero_empleado: str | None = None
    fecha_ingreso: date | None = None
    cuenta_habilitada: bool = True
    jefe: dict | None = None
    jefe_id: int | None = None          # jefe local que coincide con el manager de Microsoft
    jefe_registrado_id: int | None = None  # el manager existe en SIP-O aunque aún no esté marcado como jefe
    ubicacion: str | None = None        # "Ubicación del trabajo" (officeLocation) de Microsoft
    sede_id: int | None = None          # sede que corresponde a esa ubicación
    sede_nombre: str | None = None
    sede_nueva: bool = False            # se creó la sede a partir de la ubicación
    tiene_reportes: bool = False        # tiene personas a cargo en Microsoft: se sugiere marcarlo como jefe
    foto: str | None = None             # data URL
    ya_registrado_id: int | None = None


class RegistrarJefeIn(BaseModel):
    """Alta (o marcado como jefe) del jefe que Microsoft indica para un empleado."""
    email: str
    sede_id: int | None = None  # el jefe debe ser de la misma sede que el empleado
    numero_empleado: str | None = None  # obligatorio solo si Microsoft no tiene el employeeId


# ---------- Festivos / reglas ----------
class FestivoIn(BaseModel):
    fecha: date
    nombre: str
    aplica_a: Literal["todos", "oficina", "planta"] = "todos"


class FestivoOut(FestivoIn, ORM):
    id: int
    sede_id: int | None = None
    sede_nombre: str | None = None


class ReglaIn(BaseModel):
    anios_desde: int = Field(ge=1)
    anios_hasta: int = Field(ge=1)
    dias: int = Field(ge=1)


class ReglaOut(ReglaIn, ORM):
    id: int


# ---------- Periodos ----------
class PeriodoOut(ORM):
    id: int
    usuario_id: int
    numero: int
    nombre: str
    fecha_inicio: date
    fecha_vencimiento: date
    dias_ley: int
    horas_otorgadas: float
    horas_por_dia: int
    ajuste_horas: float
    nota_ajuste: str | None
    # saldos (horas)
    horas_total: float = 0
    horas_borrador: float = 0
    horas_solicitado: float = 0
    horas_validado: float = 0
    horas_disponible: float = 0
    # saldos (días según la categoría del empleado)
    dias_total: float = 0
    dias_borrador: float = 0
    dias_solicitado: float = 0
    dias_validado: float = 0
    dias_disponible: float = 0
    # días no usados que se perdieron porque el periodo venció (18 meses)
    horas_perdidas: float = 0
    dias_perdidos: float = 0
    # regla del bloque: al menos una vez por periodo `minimo_dias` días seguidos
    minimo_dias: int = 6
    bloque_cumplido: bool = False
    vigente: bool = True


class AjustePeriodo(BaseModel):
    ajuste_horas: float
    nota_ajuste: str | None = None


# ---------- Vacaciones ----------
class VacacionesIn(BaseModel):
    periodo_id: int | None = None  # None = modo general: primero los días del periodo más antiguo
    fecha_inicio: date
    fecha_fin: date
    comentario: str | None = None
    enviar: bool = False
    aprobador_id: int | None = None  # jefe que aprobará; por defecto el jefe directo
    firma: Firma | None = None       # obligatoria al enviar
    usuario_id: int | None = None  # solo admin: crear a nombre de otro empleado


class CalculoIn(BaseModel):
    periodo_id: int | None = None  # None = modo general
    fecha_inicio: date
    fecha_fin: date
    usuario_id: int | None = None
    excluir_id: int | None = None


class DiasLaboralesIn(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    usuario_id: int | None = None


class DiaExcluido(BaseModel):
    fecha: date
    motivo: str


class DiasLaboralesOut(BaseModel):
    """Días que se descuentan de un rango (sin depender de un periodo de vacaciones)."""
    dias_habiles: int
    horas: float
    horas_por_dia: int
    fechas: list[date]
    excluidos: list[DiaExcluido]


class TramoPeriodo(BaseModel):
    """Parte de una solicitud en modo general que se descuenta de un periodo."""
    periodo_id: int
    periodo_nombre: str
    fecha_inicio: date
    fecha_fin: date
    dias: int


class CalculoOut(BaseModel):
    dias_habiles: int
    horas: float
    errores: list[str]
    advertencias: list[str]
    fechas: list[date]
    horas_disponible: float
    dias_disponible: float
    minimo_dias: int
    reparto: list[TramoPeriodo] = []  # modo general: de qué periodo sale cada parte


class VacacionesOut(ORM):
    id: int
    usuario_id: int
    usuario_nombre: str | None = None
    periodo_id: int
    periodo_nombre: str | None = None
    fecha_inicio: date
    fecha_fin: date
    dias_habiles: int
    horas: float
    estado: str
    comentario: str | None
    motivo_rechazo: str | None
    aprobador_id: int | None = None
    aprobador_nombre: str | None = None
    tiene_firma: bool = False
    revisado_por_nombre: str | None = None
    fecha_revision: datetime | None
    creado: datetime | None


class RechazoIn(BaseModel):
    motivo: str | None = None


# ---------- Permisos ----------
class PermisoIn(BaseModel):
    tipo: TipoPermiso
    fecha: date
    fecha_fin: date | None = None       # solo home office
    hora_inicio: time | None = None     # obligatorias salvo en home office
    hora_fin: time | None = None
    motivo: str | None = None
    departamento: str | None = None
    tipo_nomina: TipoNomina | None = None
    firma: Firma | None = None
    enviar: bool = False
    aprobador_id: int | None = None
    usuario_id: int | None = None


class PermisoOut(ORM):
    id: int
    usuario_id: int
    usuario_nombre: str | None = None
    tipo: str
    fecha: date
    fecha_fin: date | None = None
    dias: int | None = None             # home office: días laborales del rango
    hora_inicio: time
    hora_fin: time
    horas: float
    motivo: str | None
    observaciones: str | None
    departamento: str | None = None
    tipo_nomina: str | None = None
    estado: str
    motivo_rechazo: str | None
    aprobador_id: int | None = None
    aprobador_nombre: str | None = None
    tiene_firma: bool = False
    revisado_por_nombre: str | None = None
    fecha_revision: datetime | None
    creado: datetime | None


class ValidarPermisoIn(BaseModel):
    observaciones: str | None = None




# ---------- Consultas médicas ----------
class MedicamentoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    dosis: str | None = Field(None, max_length=100)
    frecuencia: str | None = Field(None, max_length=100)
    duracion: str | None = Field(None, max_length=100)


class MedicamentoOut(MedicamentoIn, ORM):
    id: int


class ConsultaIn(BaseModel):
    paciente_id: int
    fecha: date
    hora_inicio: time
    hora_fin: time | None = None
    sintomas: str = Field(min_length=3)
    diagnostico: str | None = None
    indicaciones: str | None = None
    resultado: Literal["regresa_labores", "envia_casa", "referido"] = "regresa_labores"
    medicamentos: list[MedicamentoIn] = []


class ConsultaResumenOut(ORM):
    """Lo que ven el jefe y el administrador: que hubo consulta, sin información clínica."""
    id: int
    paciente_id: int
    paciente_nombre: str | None = None
    fecha: date
    hora_inicio: time
    hora_fin: time | None
    medico_nombre: str | None = None
    detalle_clinico: bool = False


class ConsultaOut(ConsultaResumenOut):
    """Detalle completo: solo el médico y el propio paciente."""
    paciente_numero: str | None = None
    paciente_rol: str | None = None
    paciente_departamento: str | None = None
    sintomas: str
    diagnostico: str | None
    indicaciones: str | None
    resultado: str
    medicamentos: list[MedicamentoOut] = []
    creado: datetime | None = None
    detalle_clinico: bool = True


class PacienteOut(ORM):
    id: int
    numero_empleado: str
    nombre: str
    rol: str
    puesto: str | None
    departamento: str | None
    tiene_foto: bool = False


# ---------- Sedes ----------
class SedeIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    ubicacion_microsoft: str | None = Field(None, max_length=200)
    zona_horaria: str = "America/Mexico_City"
    activa: bool = True


class SedeOut(SedeIn, ORM):
    id: int
    empleados: int = 0


# ---------- Política de la sede y tipos de jornada ----------
TipoPermisoSolicitable = Literal["llegada_tarde", "salida_temprana", "salida_intermedia", "home_office"]


class PoliticaIn(BaseModel):
    meses_vigencia: int = Field(18, ge=1, le=60)
    equivalencia_horas: bool = True
    dias_anticipacion: int = Field(0, ge=0, le=90)
    tipos_permiso: list[TipoPermisoSolicitable] = []
    home_office_max_dias: int = Field(31, ge=1, le=365)
    modulo_consultas: bool = True
    modulo_cumpleanos: bool = True


class JornadaIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    horas_dia: int = Field(8, ge=1, le=24)
    bloque_minimo: int = Field(6, ge=1, le=30)
    usa_ciclo_grupo: bool = False
    activo: bool = True


class JornadaOut(JornadaIn, ORM):
    id: int
    sede_id: int
    empleados: int = 0
