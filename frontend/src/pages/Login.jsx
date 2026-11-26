import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { MODO_CASETA } from '../appCaseta'

const TEXTOS = {
  es: {
    microsoft: 'Iniciar sesión con Microsoft',
    soloRegistrados: 'Solo usuarios registrados pueden acceder.',
    o: 'o',
    correo: 'Correo o número de nómina',
    password: 'Contraseña',
    entrar: 'Entrar',
    entrando: 'Entrando…',
    noConfigurado: 'El inicio de sesión con Microsoft aún no está configurado. Usa tu usuario y contraseña.',
    redirigiendo: 'Redirigiendo a Microsoft…',
    errores: {
      no_registrado: 'Tu cuenta de Microsoft no está registrada en el sistema. Pide al administrador que te dé de alta.',
      inactivo: 'Tu usuario está inactivo. Contacta al administrador.',
      cuenta_distinta: 'Este correo está vinculado a otra cuenta de Microsoft. Contacta al administrador.',
      estado_invalido: 'La solicitud de inicio de sesión expiró o no es válida. Intenta de nuevo.',
      cancelado: 'Se canceló el inicio de sesión con Microsoft.',
      no_configurado: 'El inicio de sesión con Microsoft no está configurado.',
      sesion_expirada: 'Tu sesión expiró. Inicia sesión de nuevo.',
    },
  },
  en: {
    microsoft: 'Sign in with Microsoft',
    soloRegistrados: 'Only registered users can access.',
    o: 'or',
    correo: 'Email or payroll number',
    password: 'Password',
    entrar: 'Sign in',
    entrando: 'Signing in…',
    noConfigurado: 'Microsoft sign-in is not configured yet. Use your username and password.',
    redirigiendo: 'Redirecting to Microsoft…',
    errores: {
      no_registrado: 'Your Microsoft account is not registered. Ask the administrator to add you.',
      inactivo: 'Your user is inactive. Contact the administrator.',
      cuenta_distinta: 'This email is linked to a different Microsoft account. Contact the administrator.',
      estado_invalido: 'The sign-in request expired or is invalid. Please try again.',
      cancelado: 'Microsoft sign-in was cancelled.',
      no_configurado: 'Microsoft sign-in is not configured.',
      sesion_expirada: 'Your session expired. Please sign in again.',
    },
  },
}

const errorDeUrl = () => new URLSearchParams(window.location.search).get('error')

function leerIdioma() {
  try { return localStorage.getItem('idioma') === 'en' ? 'en' : 'es' } catch { return 'es' }
}

function MicrosoftIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  )
}

export default function Login() {
  const { login, loginMicrosoft } = useAuth()
  const navigate = useNavigate()
  const [idioma, setIdioma] = useState(leerIdioma)
  const [config, setConfig] = useState({ app_nombre: 'SIP-O', app_descripcion: 'Sistema Integral de Personal O-Tek', microsoft: false, password_login: true })
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [codigoError] = useState(errorDeUrl)
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  const t = TEXTOS[idioma]
  const mensaje = error || (codigoError ? t.errores[codigoError] || codigoError : '')

  const [casetas, setCasetas] = useState([])
  const passRef = useRef(null)
  useEffect(() => { api('/auth/config').then(setConfig).catch(() => {}) }, [])
  // App de Caseta: el personal de caseta aparece al inicio para elegirse con un toque
  useEffect(() => { if (MODO_CASETA) api('/auth/usuarios-caseta').then(setCasetas).catch(() => {}) }, [])
  const elegir = (u) => { setEmail(u.usuario); setPassword(''); setError(''); setTimeout(() => passRef.current?.focus(), 0) }

  function cambiarIdioma(i) {
    setIdioma(i)
    try { localStorage.setItem('idioma', i) } catch { /* sin almacenamiento */ }
  }

  async function entrar(e) {
    e.preventDefault()
    setError('')
    setEnviando(true)
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  function entrarMicrosoft() {
    setError('')
    if (!config.microsoft) {
      setError(t.noConfigurado)
      return
    }
    setEnviando(true)
    // El backend genera state, nonce y PKCE y redirige a Microsoft; al volver deja la cookie de sesión.
    const siguiente = window.location.pathname === '/login' ? '/' : window.location.pathname
    loginMicrosoft(siguiente)
  }

  return (
    <div className="login-page">
      <img src="/logo-sip.png" alt="SIP · Sistema Integral de Personal" className="login-logo" />
      <svg className="login-ola" viewBox="0 0 1440 600" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0,0 C360,140 720,190 1000,160 C1200,140 1330,90 1440,105 L1440,600 L0,600 Z" />
      </svg>

      <div className="login-card">
        <div className="login-avatar login-avatar-sip"><img src={MODO_CASETA ? '/caseta-192.png' : '/icono-sip.png'} alt="" /></div>
        <h1>{MODO_CASETA ? `${config.app_nombre} Caseta` : config.app_nombre}</h1>
        <p className="login-sub">{MODO_CASETA ? 'Acceso para el personal de caseta' : config.app_descripcion}</p>

        {/* Por defecto: usuario y contraseña; Microsoft como opción debajo */}
        {config.password_login && (
          <form onSubmit={entrar} className="login-form">
            {MODO_CASETA && casetas.length > 0 && (
              <div className="login-casetas">
                <span>¿Quién entra?</span>
                <div>
                  {casetas.map((u) => (
                    <button key={u.usuario} type="button" className={email === u.usuario ? 'activo' : ''} onClick={() => elegir(u)}>
                      <b>{u.nombre.split(' ').filter(Boolean).map((x) => x[0]).slice(0, 2).join('')}</b>{u.nombre}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <label>{t.correo}
              <input type="text" autoFocus={!MODO_CASETA} autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required
                placeholder="nombre@o-tek.com o 2001" />
            </label>
            <label>{t.password}
              <input ref={passRef} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </label>
            <button className="login-btn" disabled={enviando}>{enviando ? t.entrando : t.entrar}</button>
          </form>
        )}
        {mensaje && <div className="login-error" role="alert">{mensaje}</div>}

        {/* La app de Caseta entra solo con usuario y contraseña */}
        {MODO_CASETA && !config.password_login && (
          <div className="login-error" role="alert">El acceso con usuario y contraseña está desactivado; pide al administrador que lo active para la app de Caseta.</div>
        )}
        {!MODO_CASETA && config.password_login && <div className="login-o"><span>{t.o}</span></div>}
        {!MODO_CASETA && (
          <button className="login-ms" onClick={entrarMicrosoft} disabled={enviando} type="button">
            <MicrosoftIcon /> {enviando && !email ? t.redirigiendo : t.microsoft}
          </button>
        )}
        <p className="login-nota">{t.soloRegistrados}</p>
      </div>

      <div className="login-idioma">
        <button className={idioma === 'es' ? 'activo' : ''} onClick={() => cambiarIdioma('es')}>ES</button>
        <span>·</span>
        <button className={idioma === 'en' ? 'activo' : ''} onClick={() => cambiarIdioma('en')}>EN</button>
      </div>
    </div>
  )
}
