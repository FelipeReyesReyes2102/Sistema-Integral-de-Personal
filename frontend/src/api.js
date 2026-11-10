// La sesión vive en una cookie HttpOnly que el navegador envía sola; aquí no se guarda ningún token.
// Para peticiones que modifican datos se reenvía el token CSRF (cookie legible) en X-CSRF-Token.

function leerCookie(nombre) {
  const par = document.cookie.split('; ').find((c) => c.startsWith(`${nombre}=`))
  return par ? decodeURIComponent(par.split('=')[1]) : ''
}

// Nombres de los campos y mensajes de validación en español (errores 422 del servidor)
const CAMPOS = {
  fecha_ingreso: 'Fecha de ingreso', numero_empleado: 'Número de nómina', nombre: 'Nombre', email: 'Correo corporativo',
  email_personal: 'Correo personal', fecha_nacimiento: 'Fecha de nacimiento', telefono: 'Teléfono', password: 'Contraseña',
  fecha: 'Fecha', fecha_inicio: 'Fecha de inicio', fecha_fin: 'Fecha de término', hora_inicio: 'Hora de inicio',
  hora_fin: 'Hora de fin', motivo: 'Motivo', rol: 'Tipo de usuario', dias_disponibles: 'Días de vacaciones disponibles',
}
function traducir(msg = '') {
  if (/required/i.test(msg)) return 'es obligatorio'
  if (/valid date|datetime/i.test(msg)) return 'no es una fecha válida'
  if (/valid time/i.test(msg)) return 'no es una hora válida'
  if (/at least (\d+) character/i.test(msg)) return `debe tener al menos ${msg.match(/at least (\d+)/i)[1]} caracteres`
  if (/at most (\d+) character/i.test(msg)) return `debe tener como máximo ${msg.match(/at most (\d+)/i)[1]} caracteres`
  if (/valid number|valid integer/i.test(msg)) return 'debe ser un número'
  if (/greater than or equal/i.test(msg)) return 'no puede ser negativo'
  return msg
}

function mensajeError(detail, status) {
  if (!detail) return `Error ${status}`
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => {
    const campo = (d.loc || []).slice(-1)[0] || ''
    return `${CAMPOS[campo] || campo}: ${traducir(d.msg)}`
  }).join(' · ')
  return JSON.stringify(detail)
}

const SIN_REDIRECCION = ['/auth/login-json', '/auth/me', '/auth/logout', '/auth/config']

// Sede elegida en el selector del menú (administradores con varias sedes). Vacío = todas sus sedes.
export function sedeActiva() {
  try { return localStorage.getItem('sip-sede') || '' } catch { return '' }
}

export function elegirSede(id) {
  try {
    if (id) localStorage.setItem('sip-sede', String(id))
    else localStorage.removeItem('sip-sede')
  } catch { /* sin almacenamiento */ }
  window.location.reload()
}

export async function api(path, { method = 'GET', body, query, sede: sedeElegida } = {}) {
  let url = `/api${path}`
  if (query) {
    const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ''))
    if ([...qs].length) url += `?${qs}`
  }
  const archivo = body instanceof FormData // archivos: el navegador pone el Content-Type con su separador
  const headers = archivo ? {} : { 'Content-Type': 'application/json' }
  if (method !== 'GET') headers['X-CSRF-Token'] = leerCookie('sip_csrf')
  const sede = sedeElegida || sedeActiva()
  if (sede) headers['X-Sede-Id'] = sede
  const res = await fetch(url, {
    method, headers, credentials: 'same-origin',
    body: archivo ? body : body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && !SIN_REDIRECCION.includes(path)) {
    window.location.href = '/login?error=sesion_expirada'
    throw new Error('Tu sesión expiró')
  }
  if (res.status === 204) return null
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new Error(mensajeError(data?.detail, res.status))
  return data
}
