import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [cargando, setCargando] = useState(true)

  // La cookie de sesión no es legible desde JS: se pregunta al backend quién es el usuario.
  useEffect(() => {
    api('/auth/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setCargando(false))
  }, [])

  const login = useCallback(async (email, password) => {
    const usuario = await api('/auth/login-json', { method: 'POST', body: { usuario: email, password } })
    setUser(usuario)
    return usuario
  }, [])

  // Vuelve a leer al usuario (p. ej. después de cambiar la contraseña temporal)
  const recargar = useCallback(async () => {
    const u = await api('/auth/me')
    setUser(u)
    return u
  }, [])

  const loginMicrosoft = useCallback((siguiente = '/') => {
    window.location.href = `/api/auth/microsoft/login?next=${encodeURIComponent(siguiente)}`
  }, [])

  const logout = useCallback(async () => {
    let url = null
    try {
      url = (await api('/auth/logout', { method: 'POST' }))?.logout_url
    } catch { /* la sesión ya no existía */ }
    setUser(null)
    // Si se entró con Microsoft, también se cierra la sesión de Microsoft
    window.location.href = url || '/login'
  }, [])

  return (
    <AuthContext.Provider value={{ user, cargando, login, loginMicrosoft, logout, recargar }}>{children}</AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
