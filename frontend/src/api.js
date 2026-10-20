// La sesión vive en una cookie HttpOnly que el navegador envía sola; aquí no se guarda ningún token.
// Para peticiones que modifican datos se reenvía el token CSRF (cookie legible) en X-CSRF-Token.

function leerCookie(nombre) {
  const par = document.cookie.split('; ').find((c) => c.startsWith(`${nombre}=`))
  return par ? decodeURIComponent(par.split('=')[1]) : ''
}

function mensajeError(detail, status) {
  if (!detail) return `Error ${status}`
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).slice(-1)[0] || ''}: ${d.msg}`).join(' · ')
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
  const headers = { 'Content-Type': 'application/json' }
  if (method !== 'GET') headers['X-CSRF-Token'] = leerCookie('sip_csrf')
  const sede = sedeElegida || sedeActiva()
  if (sede) headers['X-Sede-Id'] = sede
  const res = await fetch(url, {
    method, headers, credentials: 'same-origin',
    body: body !== undefined ? JSON.stringify(body) : undefined,
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
