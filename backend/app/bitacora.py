"""Bitácora de cambios: registra automáticamente lo que los usuarios crean, editan o eliminan.

Dos apartados:
- configuracion: sedes, política, jornadas, turnos (con horario por día y especiales), grupos, festivos,
  tabla de antigüedad, rotación, sedes que gestiona Gerencia GH y configuración de correo / Microsoft.
- vacaciones: solicitudes de vacaciones (creación, cambios, estados) y ajustes de saldo.

Se escribe dentro de la misma transacción (evento after_flush), así que si el cambio se revierte la entrada
también. Solo se registran cambios hechos por un usuario en una petición que modifica datos (POST/PUT/DELETE);
las tareas automáticas (sincronización de periodos o de la rotación) no generan ruido. Nunca se guardan
secretos: los valores cifrados aparecen como "(valor oculto)".
"""
import json
from datetime import date, datetime, time

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, object_session

from .models import (
    AdminSede, Bitacora, ConfiguracionApp, Festivo, Grupo, HorarioEspecial, PeriodoVacaciones, ReglaAntiguedad,
    ListaSharePoint, RotacionTurnos, Sede, SolicitudVacaciones, TipoJornada, Turno, TurnoDia, Usuario,
)

CONFIG, VACACIONES = "configuracion", "vacaciones"
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
DIAS_LARGOS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
ESTADOS = {"borrador": "Borrador", "solicitado": "Solicitado", "validado": "Validado", "rechazado": "Rechazado",
           "cancelado": "Cancelado"}
PERMISOS = {"llegada_tarde": "Llegada tarde", "salida_temprana": "Salida temprana", "salida_intermedia": "Salida intermedia",
            "home_office": "Home office"}

# Entidades con registro propio: (apartado, nombre visible)
PROPIAS = {
    Sede: (CONFIG, "Sede"), TipoJornada: (CONFIG, "Jornada"), Turno: (CONFIG, "Turno"), Grupo: (CONFIG, "Grupo"),
    Festivo: (CONFIG, "Festivo"), RotacionTurnos: (CONFIG, "Rotación de turnos"),
    SolicitudVacaciones: (VACACIONES, "Solicitud de vacaciones"), ListaSharePoint: (CONFIG, "Lista de SharePoint"),
}
OMITIR = {"id", "columnas", "sitio_id", "lista_id", "creado", "actualizado", "ultimo_aviso", "ultima_sincronizacion", "fecha_revision", "actualizado_por_id",
          "cifrado"}
CAMPOS = {
    "nombre": "Nombre", "ubicacion_microsoft": "Ubicación en Microsoft", "zona_horaria": "Zona horaria", "activa": "Activa",
    "activo": "Activo", "caseta_activo": "Avisos a caseta", "caseta_destinatarios": "Destinatarios de caseta",
    "caseta_tipos": "Permisos que avisan a caseta", "meses_vigencia": "Vigencia de los días (meses)",
    "equivalencia_horas": "Equivalencia en horas", "dias_anticipacion": "Anticipación (días)",
    "tipos_permiso": "Permisos habilitados", "home_office_max_dias": "Home office: máximo de días",
    "modulo_consultas": "Módulo de servicio médico", "modulo_cumpleanos": "Cumpleaños en el calendario",
    "horas_dia": "Horas por día", "bloque_minimo": "Bloque mínimo (días)", "usa_ciclo_grupo": "Días hábiles por ciclo del grupo",
    "hora_entrada": "Entrada", "hora_salida": "Salida", "horas_jornada": "Horas por jornada", "descripcion": "Descripción",
    "tipo_ciclo": "Tipo de ciclo", "dias_semana": "Días de trabajo", "dias_trabajo": "Días de trabajo (ciclo)",
    "dias_descanso": "Días de descanso (ciclo)", "fecha_inicio_ciclo": "Inicio del ciclo", "color": "Color",
    "en_rotacion": "Participa en la rotación", "rotacion_turno_inicial_id": "Turno del primer periodo", "turno_id": "Turno",
    "fecha": "Fecha", "aplica_a": "Aplica a", "fecha_inicio": "Fecha de inicio", "fecha_fin": "Fecha final",
    "semanas": "Cambio cada (semanas)", "turnos_orden": "Turnos que rotan", "turno_unico_id": "Turno si se desactiva",
    "aviso_activo": "Aviso semanal por correo", "aviso_hora": "Hora del aviso", "dias_habiles": "Días hábiles",
    "horas": "Horas", "estado": "Estado", "comentario": "Comentario", "motivo_rechazo": "Motivo de rechazo", "firma": "Firma",
    "aprobador_id": "Aprobador", "revisado_por_id": "Revisado por", "periodo_id": "Periodo", "usuario_id": "Empleado",
    "sede_id": "Sede", "tipo": "Tipo", "url": "URL", "sitio_nombre": "Sitio", "lista_nombre": "Lista",
    "mapeo": "Columnas y datos", "valores": "Equivalencia de opciones", "aprobacion_teams": "Aprobación en Teams",
    "col_decision": "Columna de decisión", "val_aprobado": "Valor de aprobado", "val_rechazado": "Valor de rechazado",
    "col_comentario": "Columna de comentarios", "col_respondio": "Columna de quién respondió", "cuenta_flujo": "Cuenta del flujo",
}
# Llaves foráneas que se muestran por nombre
NOMBRES_FK = {"usuarios": "nombre", "turnos": "nombre", "sedes": "nombre", "grupos": "nombre", "tipos_jornada": "nombre"}


# ---------------- Formato de valores ----------------
def _fmt(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v)
    return s if len(s) <= 300 else s[:297] + "…"


def _lista_dias(s: str | None) -> str | None:
    dias = [int(x) for x in (s or "").split(",") if x.strip().isdigit() and int(x) < 7]
    return ", ".join(DIAS[d] for d in sorted(dias)) or None


class _Ctx:
    """Consultas de nombres con caché, sobre la conexión de la transacción en curso."""

    def __init__(self, session: Session):
        self.con = session.connection()
        self.cache: dict = {}

    def nombre(self, tabla: str, id_) -> str | None:
        if id_ is None:
            return None
        clave = (tabla, id_)
        if clave not in self.cache:
            if tabla == "periodos_vacaciones":
                t = PeriodoVacaciones.__table__
                fi = self.con.execute(select(t.c.fecha_inicio).where(t.c.id == id_)).scalar()
                self.cache[clave] = f"Periodo {fi.year}" if fi else f"#{id_}"
            else:
                t = Base_tabla(tabla)
                self.cache[clave] = self.con.execute(select(t.c[NOMBRES_FK[tabla]]).where(t.c.id == id_)).scalar() or f"#{id_}"
        return self.cache[clave]

    def columna(self, tabla, col, id_):
        if id_ is None:
            return None
        clave = (tabla.name, col, id_)
        if clave not in self.cache:
            self.cache[clave] = self.con.execute(select(tabla.c[col]).where(tabla.c.id == id_)).scalar()
        return self.cache[clave]


def Base_tabla(nombre):
    from .models import Base
    return Base.metadata.tables[nombre]


def _valor(ctx: _Ctx, obj, col, v):
    """Valor legible de una columna."""
    if v is None:
        return None
    if col.key == "firma":
        return "(firma)"
    if col.key in ("estado",):
        return ESTADOS.get(v, v)
    if col.key in ("dias_semana",):
        return _lista_dias(v)
    if col.key in ("tipos_permiso", "caseta_tipos"):
        return ", ".join(PERMISOS.get(x, x) for x in v.split(",") if x) or None
    if col.key == "turnos_orden":
        return " → ".join(ctx.nombre("turnos", int(x)) for x in v.split(",") if x.strip().isdigit()) or None
    if col.key in ("mapeo", "valores"):
        try:
            d = json.loads(v or "{}")
        except ValueError:
            return _fmt(v)
        return _fmt("; ".join(f"{k}: {x}" for k, x in d.items())) if d else None
    if col.key == "aviso_hora":
        return f"{int(v):02d}:00"
    fks = list(col.foreign_keys)
    if fks:
        tabla = fks[0].column.table.name
        if tabla in NOMBRES_FK or tabla == "periodos_vacaciones":
            return ctx.nombre(tabla, v)
    return _fmt(v)


def _columnas(obj):
    return [c for c in inspect(type(obj)).columns if c.key not in OMITIR]


def _viejo(obj, key):
    """Valor anterior de un atributo (o el actual si no cambió)."""
    h = inspect(obj).attrs[key].history
    if h.deleted:
        return h.deleted[0]
    if h.unchanged:
        return h.unchanged[0]
    return getattr(obj, key) if not h.added else None


def _cambio(obj, key) -> bool:
    return inspect(obj).attrs[key].history.has_changes()


# ---------------- Entidades "hijas": se agrupan en una sola entrada del padre ----------------
def _hija(ctx: _Ctx, obj, viejo: bool):
    """(apartado, entidad, id del padre, sede_id, descripción, campo, resumen) o None si no se registra."""
    g = (lambda k: _viejo(obj, k)) if viejo else (lambda k: getattr(obj, k))
    if isinstance(obj, TurnoDia):
        t = Turno.__table__
        tid = g("turno_id")
        return (CONFIG, "Turno", tid, ctx.columna(t, "sede_id", tid), ctx.nombre("turnos", tid),
                f"Horario {DIAS_LARGOS[g('dia')]}", f"{_fmt(g('hora_entrada'))}–{_fmt(g('hora_salida'))}")
    if isinstance(obj, HorarioEspecial):
        t = Turno.__table__
        tid = g("turno_id")
        cada = g("cada_semanas") or 1
        partes = [f"{_lista_dias(g('dias'))} {_fmt(g('hora_entrada'))}–{_fmt(g('hora_salida'))}",
                  "todas las semanas" if cada == 1 else f"cada {cada} semanas",
                  f"del {_fmt(g('fecha_inicio'))}" + (f" al {_fmt(g('fecha_fin'))}" if g("fecha_fin") else " sin fecha de fin")]
        if not g("activo"):
            partes.append("inactivo")
        return (CONFIG, "Turno", tid, ctx.columna(t, "sede_id", tid), ctx.nombre("turnos", tid),
                f"Horario especial «{g('nombre')}»", " · ".join(partes))
    if isinstance(obj, ReglaAntiguedad):
        sid = g("sede_id")
        return (CONFIG, "Tabla de antigüedad", sid, sid, ctx.nombre("sedes", sid) if sid else "General",
                f"{g('anios_desde')}–{g('anios_hasta')} años", f"{g('dias')} días")
    if isinstance(obj, AdminSede):
        uid, sid = g("usuario_id"), g("sede_id")
        return (CONFIG, "Sedes de Gerencia GH", uid, sid, ctx.nombre("usuarios", uid),
                f"Gestiona {ctx.nombre('sedes', sid)}", "Sí")
    if isinstance(obj, ConfiguracionApp):
        clave = g("clave")
        grupo = "Configuración de correo" if clave.startswith("CORREO_") else (
            "Inicio de sesión con Microsoft" if clave.startswith(("MICROSOFT_", "AZURE_", "GRAPH_")) else "Configuración del sistema")
        oculto = g("cifrado") or any(p in clave for p in ("SECRET", "PASSWORD", "CLAVE", "TOKEN"))
        v = g("valor")
        return (CONFIG, grupo, None, None, grupo, clave.replace("_", " ").capitalize(),
                ("(valor oculto)" if oculto else _fmt(v)) if v not in (None, "") else None)
    if isinstance(obj, PeriodoVacaciones):
        uid = g("usuario_id")
        aj = g("ajuste_horas") or 0
        u = Usuario.__table__
        return (VACACIONES, "Saldo de vacaciones", uid, ctx.columna(u, "sede_id", uid), ctx.nombre("usuarios", uid),
                f"Ajuste del periodo {g('fecha_inicio').year}",
                (f"{_fmt(float(aj))} h" + (f" ({g('nota_ajuste')})" if g("nota_ajuste") else "")) if aj else None)
    return None


HIJAS = (TurnoDia, HorarioEspecial, ReglaAntiguedad, AdminSede, ConfiguracionApp, PeriodoVacaciones)


def _sede_de(ctx: _Ctx, obj, viejo=False):
    g = (lambda k: _viejo(obj, k)) if viejo else (lambda k: getattr(obj, k))
    if isinstance(obj, Sede):
        return obj.id
    if isinstance(obj, SolicitudVacaciones):
        return ctx.columna(Usuario.__table__, "sede_id", g("usuario_id"))
    return g("sede_id") if hasattr(obj, "sede_id") else None


def _descripcion(ctx: _Ctx, obj, viejo=False) -> str:
    g = (lambda k: _viejo(obj, k)) if viejo else (lambda k: getattr(obj, k))
    if isinstance(obj, SolicitudVacaciones):
        return (f"{ctx.nombre('usuarios', g('usuario_id'))} · {_fmt(g('fecha_inicio'))} al {_fmt(g('fecha_fin'))}"
                f" ({g('dias_habiles')} día(s))")
    if isinstance(obj, Festivo):
        return f"{_fmt(g('fecha'))} · {g('nombre')}"
    if isinstance(obj, RotacionTurnos):
        return "Rotación de turnos"
    if isinstance(obj, ListaSharePoint):
        return f"{'Vacaciones' if g('tipo') == 'vacaciones' else 'Permisos'} → {g('lista_nombre')}"
    return str(g("nombre"))


# ---------------- Registro ----------------
def _registrar(session: Session, _ctx_flush):
    actor = session.info.get("bitacora_actor")
    if not actor:
        return
    with session.no_autoflush:
        ctx = _Ctx(session)
        entradas: dict = {}  # (apartado, entidad, id) -> entrada

        def entrada(apartado, entidad, id_, sede_id, desc, accion):
            k = (apartado, entidad, id_ if id_ is not None else desc)
            if k not in entradas:
                entradas[k] = {"seccion": apartado, "entidad": entidad, "entidad_id": None if id_ is None else str(id_),
                               "sede_id": sede_id, "descripcion": desc, "accion": accion, "cambios": {}}
            elif accion != "editar":
                entradas[k]["accion"] = accion
            return entradas[k]

        def cambio(e, campo, antes, despues):
            prev = e["cambios"].get(campo)
            antes = prev[0] if prev else antes
            e["cambios"][campo] = (antes, despues)

        nuevos, sucios = list(session.new), list(session.dirty)
        # Incluye los eliminados en cascada (p. ej. un horario especial que se quitó de la lista del turno)
        borrados = list(dict.fromkeys([*session.deleted, *session.info.pop("bitacora_borrados", [])]))

        # 1) Entidades propias
        for obj in nuevos:
            if type(obj) in PROPIAS:
                ap, ent = PROPIAS[type(obj)]
                e = entrada(ap, ent, obj.id, _sede_de(ctx, obj), _descripcion(ctx, obj), "crear")
                for c in _columnas(obj):
                    v = _valor(ctx, obj, c, getattr(obj, c.key))
                    if v is not None and c.key != "sede_id":
                        cambio(e, CAMPOS.get(c.key, c.key), None, v)
        for obj in sucios:
            if type(obj) in PROPIAS and session.is_modified(obj, include_collections=False):
                ap, ent = PROPIAS[type(obj)]
                cols = [c for c in _columnas(obj) if _cambio(obj, c.key)]
                difs = [(c, _valor(ctx, obj, c, _viejo(obj, c.key)), _valor(ctx, obj, c, getattr(obj, c.key))) for c in cols]
                difs = [d for d in difs if d[1] != d[2]]
                if not difs:
                    continue
                accion = "estado" if any(c.key == "estado" for c, _, _ in difs) else "editar"
                e = entrada(ap, ent, obj.id, _sede_de(ctx, obj), _descripcion(ctx, obj), accion)
                for c, a, d in difs:
                    cambio(e, CAMPOS.get(c.key, c.key), a, d)
        for obj in borrados:
            if type(obj) in PROPIAS:
                ap, ent = PROPIAS[type(obj)]
                e = entrada(ap, ent, obj.id, _sede_de(ctx, obj, True), _descripcion(ctx, obj, True), "eliminar")
                for c in _columnas(obj):
                    v = _valor(ctx, obj, c, _viejo(obj, c.key))
                    if v is not None and c.key != "sede_id":
                        cambio(e, CAMPOS.get(c.key, c.key), v, None)

        # 2) Hijas: se agrupan en la entrada del padre (p. ej. el horario por día dentro del turno)
        for lista, viejo, nuevo in ((borrados, True, False), (sucios, True, True), (nuevos, False, True)):
            for obj in lista:
                if not isinstance(obj, HIJAS):
                    continue
                if lista is sucios and not session.is_modified(obj, include_collections=False):
                    continue
                if isinstance(obj, PeriodoVacaciones) and lista is sucios and not (
                        _cambio(obj, "ajuste_horas") or _cambio(obj, "nota_ajuste")):
                    continue
                if isinstance(obj, PeriodoVacaciones) and lista is borrados:
                    continue
                antes = _hija(ctx, obj, True) if viejo else None
                despues = _hija(ctx, obj, False) if nuevo else None
                base = despues or antes
                if not base:
                    continue
                ap, ent, pid, sid, desc, campo, _ = base
                e = entrada(ap, ent, pid, sid, desc, "editar")
                if antes and despues and antes[5] != despues[5]:  # cambió la llave (p. ej. el nombre del especial)
                    cambio(e, antes[5], antes[6], None)
                    cambio(e, despues[5], None, despues[6])
                else:
                    cambio(e, campo, antes[6] if antes else None, despues[6] if despues else None)

        filas = []
        for e in entradas.values():
            cambios = [{"campo": k, "antes": a, "despues": d} for k, (a, d) in e["cambios"].items() if a != d]
            if not cambios and e["accion"] == "editar":
                continue
            filas.append({
                "fecha": actor["fecha"], "seccion": e["seccion"], "accion": e["accion"], "entidad": e["entidad"],
                "entidad_id": e["entidad_id"], "descripcion": (e["descripcion"] or "")[:255], "sede_id": e["sede_id"],
                "sede_nombre": ctx.nombre("sedes", e["sede_id"]) if e["sede_id"] else None,
                "actor_id": actor["id"], "actor_nombre": actor["nombre"], "ip": actor["ip"],
                "cambios": json.dumps(cambios, ensure_ascii=False),
            })
        if filas:
            ctx.con.execute(Bitacora.__table__.insert(), filas)


def _al_borrar(_mapper, _con, obj):
    s = object_session(obj)
    if s is not None and s.info.get("bitacora_actor"):
        s.info.setdefault("bitacora_borrados", []).append(obj)


def activar():
    event.listen(Session, "after_flush", _registrar)
    for cls in (*PROPIAS, *HIJAS):
        event.listen(cls, "after_delete", _al_borrar)


def asignar_actor(db: Session, usuario: Usuario, ip: str | None):
    from .security import ahora
    db.info["bitacora_actor"] = {"id": usuario.id, "nombre": usuario.nombre, "ip": ip, "fecha": ahora()}
