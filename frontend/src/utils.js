export const ESTADOS = {
  borrador: 'Borrador',
  solicitado: 'Solicitado',
  validado: 'Validado',
  rechazado: 'Rechazado',
  cancelado: 'Cancelado',
}

export const TIPOS_PERMISO = {
  llegada_tarde: 'Llegada tarde',
  salida_temprana: 'Salida temprana',
  salida_intermedia: 'Salida durante la jornada',
  consulta_medica: 'Consulta médico de planta',
  home_office: 'Home office',
}

export const TIPOS_NOMINA = {
  con_goce: 'Con goce de sueldo',
  sin_goce: 'Sin goce de sueldo',
  reposicion: 'Reposición de tiempo',
}

export const ROLES = {
  superadmin: 'Super administrador', gerencia_gh: 'Gerencia GH', admin: 'GH', oficina: 'Oficinas', planta: 'Planta',
  medico: 'Médico de planta', caseta: 'Caseta',
}

/** GH, Gerencia GH o super administrador (el super administrador tiene acceso a todo). */
export const esAdmin = (u) => ['admin', 'gerencia_gh', 'superadmin'].includes(u?.rol)
export const esSuperAdmin = (u) => u?.rol === 'superadmin'
/** Médico de planta o usuario al que GH le permitió registrar consultas médicas. */
export const esMedico = (u) => ['medico', 'superadmin'].includes(u?.rol) || !!u?.puede_consultas
/** Personal de caseta (y GH): permisos validados del día y registro de retardos. */
export const esCaseta = (u) => u?.rol === 'caseta' || esAdmin(u)
/** El médico de planta y caseta no piden vacaciones ni permisos: solo usan su apartado. */
export const sinVacaciones = (u) => ['medico', 'caseta'].includes(u?.rol)
/** Pantalla de inicio de cada tipo de usuario. */
export const inicioDe = (u) => (u?.rol === 'medico' ? '/consultas' : u?.rol === 'caseta' ? '/caseta' : '/')

// Permisos que el empleado puede pedir (las consultas médicas las registra el médico)
export const TIPOS_PERMISO_SOLICITABLES = {
  llegada_tarde: 'Llegada tarde',
  salida_temprana: 'Salida temprana',
  salida_intermedia: 'Salida durante la jornada',
  home_office: 'Home office',
}

// Categorías de eventos del calendario (mismo color en todas las vistas)
export const CATEGORIAS = {
  vacaciones: { label: 'Vacaciones', color: '#2f6db5' },
  home_office: { label: 'Home office', color: '#2e9d5b' },
  llegada_tarde: { label: 'Llegada tarde', color: '#8e44ad' },
  salida_temprana: { label: 'Salida temprana', color: '#e67e22' },
  salida_intermedia: { label: 'Salida durante la jornada', color: '#c2185b' },
  otro_permiso: { label: 'Otros permisos', color: '#6d4c41' },
  consulta: { label: 'Consulta médica', color: '#00897b' },
  consulta_medica: { label: 'Consulta médica (permiso)', color: '#00897b' },
  incapacidad: { label: 'Incapacidad', color: '#b23c17' },
  festivo: { label: 'Festivo', color: '#e53935' },
  cumpleanos: { label: 'Cumpleaños', color: '#ec407a' },
  aniversario: { label: 'Aniversario', color: '#c99a06' },
}

/** Nombre visible del tipo de un permiso (los agregados por la sede traen su nombre del backend). */
export const nombreTipo = (p) => p?.tipo_nombre || TIPOS_PERMISO[p?.tipo] || p?.tipo || ''

/** "2 día(s) por mes", "8 h por año", "3 día(s) en total". */
export function textoLimite(t) {
  if (!t?.limite_cantidad) return 'Sin límite'
  const unidad = t.limite_unidad === 'horas' ? 'h' : t.modalidad === 'horas' ? 'permiso(s)' : 'día(s)'
  const periodo = { mes: 'por mes', anio: 'por año' }[t.limite_periodo] || 'en total'
  return `${Number(t.limite_cantidad).toLocaleString('es-MX')} ${unidad} ${periodo}`
}

/** Estilo de un evento según su estado: validado = sólido, solicitado = tenue, borrador = contorno. */
export function estiloEvento(cat, estado) {
  const color = CATEGORIAS[cat]?.color || '#888'
  if (estado === 'borrador') return { background: '#fff', color, boxShadow: `inset 0 0 0 1.5px ${color}` }
  if (estado === 'solicitado') return { background: `${color}38`, color: '#1d2433', boxShadow: `inset 0 0 0 1px ${color}80` }
  return { background: color, color: '#fff' }
}

/** Eventos de un día a partir de la respuesta de /api/calendario, agrupados por fecha. */
export function eventosPorFecha(datos) {
  const mapa = {}
  const agregar = (f, e) => (mapa[f] ||= []).push(e)
  for (const [f, v] of Object.entries(datos?.vacaciones || {})) agregar(f, { cat: 'vacaciones', estado: v.estado, id: v.id })
  for (const p of datos?.permisos || []) agregar(p.fecha, { cat: p.cat || p.tipo, tipo_nombre: p.tipo_nombre, estado: p.estado, id: p.id, hora_inicio: p.hora_inicio, hora_fin: p.hora_fin })
  for (const i of datos?.incapacidades || []) agregar(i.fecha, { cat: 'incapacidad', estado: i.estado, id: i.id })
  for (const c of datos?.consultas || []) agregar(c.fecha, { cat: 'consulta', estado: 'registrada', id: c.id, hora_inicio: c.hora_inicio, hora_fin: c.hora_fin })
  return mapa
}

/** "1990-05-14" -> "14 de mayo" (los cumpleaños nunca muestran el año). */
export function diaMes(iso) {
  if (!iso) return ''
  return parseISO(iso).toLocaleDateString('es-MX', { day: 'numeric', month: 'long' })
}

export const TIPOS_INCAPACIDAD = {
  enfermedad_general: 'Enfermedad general',
  riesgo_trabajo: 'Riesgo de trabajo',
  maternidad: 'Maternidad',
  otro: 'Otro',
}

export const ESTADOS_INCAPACIDAD = { solicitado: 'Por validar', validado: 'Validada', rechazado: 'Rechazada' }

export const RESULTADOS_CONSULTA = {
  regresa_labores: 'Regresa a sus labores',
  envia_casa: 'Se envía a casa',
  referido: 'Referido a clínica / IMSS',
}

export const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre',
  'Octubre', 'Noviembre', 'Diciembre']

export const DIAS_SEMANA = ['Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sa', 'Do']

/** "2024-08-12" -> Date local (sin desfase de zona horaria) */
export function parseISO(iso) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function toISO(date) {
  const p = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`
}

export function fmtFecha(iso, conDia = true) {
  if (!iso) return ''
  const d = parseISO(iso)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yy = String(d.getFullYear()).slice(-2)
  const dia = d.toLocaleDateString('es-MX', { weekday: 'short' }).replace('.', '')
  return conDia ? `${dia} ${dd}/${mm}/${yy}` : `${dd}/${mm}/${d.getFullYear()}`
}

export const hhmm = (t) => (t ? t.slice(0, 5) : '')

export function num(n, dec = 2) {
  if (n === null || n === undefined) return '0'
  return Number(Number(n).toFixed(dec)).toString()
}

export function horasEntre(ini, fin) {
  if (!ini || !fin) return 0
  const [h1, m1] = ini.split(':').map(Number)
  const [h2, m2] = fin.split(':').map(Number)
  let mins = h2 * 60 + m2 - (h1 * 60 + m1)
  if (mins <= 0) mins += 24 * 60
  return Math.round((mins / 60) * 100) / 100
}

export const hoyISO = () => toISO(new Date())
