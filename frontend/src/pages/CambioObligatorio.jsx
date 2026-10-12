import { useState } from 'react'
import { KeyRound, LogOut } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'

const segura = (p) => p.length >= 8 && /[A-Za-zÁÉÍÓÚáéíóúÑñ]/.test(p) && /\d/.test(p)

/** Primer inicio de sesión: el empleado debe reemplazar su contraseña temporal de 6 dígitos. */
export default function CambioObligatorio() {
  const { user, recargar, logout } = useAuth()
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [confirma, setConfirma] = useState('')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  async function guardar(e) {
    e.preventDefault()
    setError('')
    if (!segura(nueva)) return setError('La contraseña nueva debe tener al menos 8 caracteres e incluir letras y números.')
    if (nueva !== confirma) return setError('Las contraseñas nuevas no coinciden.')
    if (nueva === actual) return setError('La contraseña nueva debe ser distinta de la temporal.')
    setGuardando(true)
    try {
      await api('/auth/cambiar-password', { method: 'POST', body: { actual, nueva } })
      await recargar()
    } catch (err) {
      setError(err.message)
    } finally {
      setGuardando(false)
    }
  }

  return (
    <div className="login-page">
      <img src="/logo-otek.png" alt="O-tek" className="login-logo" />
      <svg className="login-ola" viewBox="0 0 1440 600" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0,0 C360,140 720,190 1000,160 C1200,140 1330,90 1440,105 L1440,600 L0,600 Z" />
      </svg>
      <div className="login-card">
        <div className="login-avatar"><KeyRound size={30} /></div>
        <h1>Crea tu contraseña</h1>
        <p className="login-sub">
          Hola {user.nombre.split(' ')[0]}, entraste con una contraseña temporal. Para continuar, crea una contraseña personal.
        </p>
        <form onSubmit={guardar} className="login-form">
          <label>Contraseña temporal (6 dígitos)
            <input type="password" inputMode="numeric" autoFocus value={actual} onChange={(e) => setActual(e.target.value)} required
              autoComplete="current-password" />
          </label>
          <label>Contraseña nueva
            <input type="password" value={nueva} onChange={(e) => setNueva(e.target.value)} required autoComplete="new-password" />
          </label>
          <label>Confirmar contraseña nueva
            <input type="password" value={confirma} onChange={(e) => setConfirma(e.target.value)} required autoComplete="new-password" />
          </label>
          <ul className="login-reglas">
            <li className={nueva.length >= 8 ? 'ok' : ''}>Al menos 8 caracteres</li>
            <li className={/[A-Za-zÁÉÍÓÚáéíóúÑñ]/.test(nueva) && /\d/.test(nueva) ? 'ok' : ''}>Letras y números</li>
            <li className={nueva && nueva === confirma ? 'ok' : ''}>Ambas coinciden</li>
          </ul>
          <button className="login-btn" disabled={guardando}>{guardando ? 'Guardando…' : 'Guardar y entrar'}</button>
        </form>
        {error && <div className="login-error" role="alert">{error}</div>}
        <div className="login-sep" />
        <button className="login-link" onClick={logout}><LogOut size={13} style={{ verticalAlign: -2 }} /> Salir</button>
      </div>
    </div>
  )
}
