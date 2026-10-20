import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'

const CAMPOS = ['email_personal', 'fecha_nacimiento', 'telefono', 'direccion', 'contacto_nombre', 'contacto_telefono']

/**
 * Datos personales que el propio usuario puede actualizar. Al guardar (con o sin cambios) quedan confirmados
 * y vuelven a contar los 6 meses para la siguiente confirmación.
 */
export default function MisDatosForm({ textoGuardar = 'Guardar mis datos', onGuardado, pieExtra = null }) {
  const { user, recargar } = useAuth()
  const [form, setForm] = useState(Object.fromEntries(CAMPOS.map((k) => [k, user[k] || ''])))
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const cambio = CAMPOS.some((k) => (form[k] || '') !== (user[k] || ''))

  async function guardar(e) {
    e.preventDefault()
    setError('')
    setGuardando(true)
    try {
      await api('/auth/mis-datos', { method: 'PUT', body: Object.fromEntries(CAMPOS.map((k) => [k, (form[k] || '').trim() || null])) })
      await recargar()
      onGuardado?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setGuardando(false)
    }
  }

  return (
    <form onSubmit={guardar} className="mis-datos">
      <div className="mis-datos-fijos">
        <div><span>Nombre</span><b>{user.nombre}</b></div>
        <div><span>No. de nómina</span><b>{user.numero_empleado}</b></div>
        {user.email && <div><span>Correo corporativo</span><b>{user.email}</b></div>}
        {user.puesto && <div><span>Puesto</span><b>{user.puesto}</b></div>}
      </div>
      <div className="form-grid">
        <label className="campo">Teléfono<input type="tel" value={form.telefono} onChange={set('telefono')} placeholder="Ej. 55 1234 5678" autoFocus /></label>
        <label className="campo">Correo personal<input type="email" value={form.email_personal} onChange={set('email_personal')} placeholder="nombre@gmail.com" /></label>
        <label className="campo full">Dirección<input value={form.direccion} onChange={set('direccion')} placeholder="Calle, número, colonia, ciudad" /></label>
        <label className="campo">Contacto de emergencia (nombre)<input value={form.contacto_nombre} onChange={set('contacto_nombre')} placeholder="Ej. María López (esposa)" /></label>
        <label className="campo">Número de contacto<input type="tel" value={form.contacto_telefono} onChange={set('contacto_telefono')} placeholder="Ej. 55 8765 4321" /></label>
        <label className="campo">Fecha de nacimiento<input type="date" value={form.fecha_nacimiento} onChange={set('fecha_nacimiento')} /></label>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '10px 0 0' }}>
        Tu nombre, nómina, puesto y datos laborales los actualiza Gestión Humana. Cada 6 meses te pediremos confirmar estos datos.
      </p>
      {error && <div className="alerta error">{error}</div>}
      <div className="fila" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
        {pieExtra}
        <button className="btn btn-primary" disabled={guardando}>{guardando ? 'Guardando…' : cambio ? textoGuardar : textoGuardar.replace('Guardar', 'Confirmar')}</button>
      </div>
    </form>
  )
}
