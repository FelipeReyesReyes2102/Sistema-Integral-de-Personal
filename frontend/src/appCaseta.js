/**
 * App de Caseta para Android (aplicación web instalable, ver public/caseta.webmanifest).
 *
 * Se abre en "modo caseta" cuando:
 *  - la dirección trae ?app=caseta (así arranca la app instalada: es su start_url), o
 *  - ya se abrió así en esta ventana (sessionStorage), o
 *  - corre instalada a pantalla completa (display-mode standalone): SIP-O solo se instala como app de Caseta.
 *
 * En modo caseta solo existe la pantalla de Caseta. Es una restricción de interfaz: los permisos reales
 * los sigue exigiendo el backend (require_caseta).
 */
const CLAVE = 'sip-app-caseta'

function detectar() {
  try {
    if (new URLSearchParams(window.location.search).get('app') === 'caseta') sessionStorage.setItem(CLAVE, '1')
    if (sessionStorage.getItem(CLAVE) === '1') return true
  } catch { /* sin almacenamiento */ }
  try {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true
  } catch {
    return false
  }
}

export const MODO_CASETA = detectar()

export const INICIO_CASETA = '/caseta?app=caseta'

/** Registra el service worker mínimo (requisito para que Chrome ofrezca "Instalar app"). */
export function registrarAppCaseta() {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return
  const enCaseta = MODO_CASETA || window.location.pathname.startsWith('/caseta')
  if (!enCaseta) return
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw-caseta.js').catch(() => { /* sin service worker: la app web sigue funcionando */ })
  })
}
