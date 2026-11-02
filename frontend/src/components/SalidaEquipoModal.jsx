import { useState } from 'react'
import { api } from '../api'
import { esAdmin, hoyISO } from '../utils'
import { useAuth } from '../auth'
import FormularioOtek, { Campo } from './FormularioOtek'
import SelectorJefe from './SelectorJefe'

/** Solicitud de salida de equipo de cómputo (formato F-630-03): datos del equipo, plazo, jefe y firma. */
export default function SalidaEquipoModal({ salida, usuario, onClose, onSaved }) {
  const { user } = useAuth()
  const empleado = usuario || user
  const [form, setForm] = useState({
    tipo_equipo: salida?.tipo_equipo || 'laptop', marca: salida?.marca || '', modelo: salida?.modelo || '', serie: salida?.serie || '',
    accesorios: salida?.accesorios || '', justificacion: salida?.justificacion || '',
    fecha_inicio: salida?.fecha_inicio || hoyISO(), fecha_fin: salida?.fecha_fin || hoyISO(), detalles: salida?.detalles || '',
    aprobador_id: salida?.aprobador_id || null,
  })
  const [firma, setFirma] = useState(null)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const requiereJefe = !esAdmin(empleado)
  const completo = form.marca.trim() && form.modelo.trim() && form.serie.trim().length >= 2 && form.justificacion.trim().length >= 3
    && form.fecha_inicio && form.fecha_fin >= form.fecha_inicio && (!requiereJefe || form.aprobador_id)
  const dias = form.fecha_inicio && form.fecha_fin >= form.fecha_inicio
    ? Math.round((new Date(form.fecha_fin) - new Date(form.fecha_inicio)) / 864e5) + 1 : 0

  async function guardar(enviar) {
    setError('')
    setGuardando(true)
    const body = {
      ...form, enviar, firma, usuario_id: usuario && usuario.id !== user.id ? usuario.id : null,
      accesorios: form.accesorios.trim() || null, detalles: form.detalles.trim() || null,
    }
    try {
      if (salida) await api(`/equipos/${salida.id}`, { method: 'PUT', body })
      else await api('/equipos', { method: 'POST', body })
      window.dispatchEvent(new Event('pendientes:refrescar'))
      onSaved()
    } catch (e) {
      setError(e.message)
    } finally {
      setGuardando(false)
    }
  }

  return (
    <FormularioOtek titulo="Entrada y salida de equipos de cómputo" subtitulo={usuario && usuario.id !== user.id ? `Para: ${usuario.nombre}` : 'Formato F-630-03'}
      onClose={onClose} onFirma={setFirma} enviando={guardando} enviarDeshabilitado={!completo || !firma} onEnviar={() => guardar(true)}
      pieExtra={<button className="btn btn-sm" disabled={!completo || guardando} onClick={() => guardar(false)}>Guardar borrador</button>}>
      <Campo label="Tipo de equipo" requerido full>
        <div className="fila" style={{ gap: 18 }}>
          <label className="checkbox"><input type="radio" name="tipo_equipo" checked={form.tipo_equipo === 'laptop'} onChange={() => setForm({ ...form, tipo_equipo: 'laptop' })} /> Laptop</label>
          <label className="checkbox"><input type="radio" name="tipo_equipo" checked={form.tipo_equipo === 'escritorio'} onChange={() => setForm({ ...form, tipo_equipo: 'escritorio' })} /> De escritorio</label>
        </div>
      </Campo>
      <Campo label="Marca" requerido><input value={form.marca} onChange={set('marca')} maxLength={80} placeholder="Ej. Dell" /></Campo>
      <Campo label="Modelo" requerido><input value={form.modelo} onChange={set('modelo')} maxLength={80} placeholder="Ej. Latitude 5440" /></Campo>
      <Campo label="SN / Service Tag" requerido><input value={form.serie} onChange={set('serie')} maxLength={80} placeholder="Número de serie" /></Campo>
      <Campo label="Accesorios"><input value={form.accesorios} onChange={set('accesorios')} maxLength={255} placeholder="Ej. cargador, mouse, maletín" /></Campo>
      <Campo label="Justificación" requerido full>
        <textarea className="fo-textarea" rows={2} value={form.justificacion} onChange={set('justificacion')} maxLength={2000}
          placeholder="Para qué y a dónde sale el equipo" />
      </Campo>
      <Campo label="Plazo: fecha inicio" requerido>
        <input type="date" value={form.fecha_inicio} min={esAdmin(user) ? undefined : hoyISO()}
          onChange={(e) => setForm({ ...form, fecha_inicio: e.target.value, fecha_fin: form.fecha_fin < e.target.value ? e.target.value : form.fecha_fin })} />
      </Campo>
      <Campo label="Fecha término" requerido ayuda={dias ? `${dias} día(s)` : null}>
        <input type="date" value={form.fecha_fin} min={form.fecha_inicio} onChange={set('fecha_fin')} />
      </Campo>
      <Campo label="Detalles del equipo" full>
        <input value={form.detalles} onChange={set('detalles')} maxLength={2000} placeholder="Ej. activo fijo, estado, número de inventario" />
      </Campo>
      <Campo label="Jefe directo (autoriza)" requerido={requiereJefe} full>
        <SelectorJefe empleado={empleado} value={form.aprobador_id} onChange={(v) => setForm((f) => ({ ...f, aprobador_id: v }))} />
      </Campo>
      <div className="full fo-mensajes">
        <div className="fo-ayuda">Tu jefe directo la autoriza en SIP-O. TI puede revisarla y rechazarla antes de que el equipo salga; caseta registra la salida y el regreso.</div>
        {error && <div className="alerta error">{error}</div>}
        {completo && !firma && <div className="fo-ayuda">Firma en el recuadro de la derecha para enviar.</div>}
      </div>
    </FormularioOtek>
  )
}
