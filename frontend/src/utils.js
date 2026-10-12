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
  superadmin: 'Super administrador', admin: 'Administrador', oficina: 'Oficinas', planta: 'Planta', medico: 'Médico de planta',
}

/** Administrador o super administrador (el super administrador tiene acceso a todo). */
export const esAdmin = (u) => u?.rol === 'admin' || u?.rol === 'superadmin'
export const esSuperAdmin = (u) => u?.rol === 'superadmin'

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
  consulta: { label: 'Consulta médica', color: '#00897b' },
  consulta_medica: { label: 'Consulta médica (permiso)', color: '#00897b' },
  festivo: { label: 'Festivo', color: '#e53935' },
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
  for (const p of datos?.permisos || []) agregar(p.fecha, { cat: p.tipo, estado: p.estado, id: p.id, hora_inicio: p.hora_inicio, hora_fin: p.hora_fin })
  for (const c of datos?.consultas || []) agregar(c.fecha, { cat: 'consulta', estado: 'registrada', id: c.id, hora_inicio: c.hora_inicio, hora_fin: c.hora_fin })
  return mapa
}

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
