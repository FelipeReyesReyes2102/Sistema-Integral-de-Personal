import { useEffect, useState } from 'react'
import { Save, Send, Server } from 'lucide-react'
import { api } from '../api'

/** Servidor de correo común a todas las sedes (solo super administrador). */
export default function ConfigCorreoServidor() {
  const [guardado, setGuardado] = useState(null)
  const [form, setForm] = useState(null)
  const [password, setPassword] = useState('')
  const [borrarPassword, setBorrarPassword] = useState(false)
  const [prueba, setPrueba] = useState('')
  const [msg, setMsg] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  const aplicar = (r) => {
    setGuardado(r)
    const { password_configurada, ...valores } = r
    setForm(valores)
    setPassword('')
    setBorrarPassword(false)
  }
  useEffect(() => { api('/admin/correo/servidor').then(aplicar).catch((e) => setMsg({ ok: false, t: e.message })) }, [])
  if (!form) return <div className="card">{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const set = (k, conv = (v) => v) => (e) => setForm({ ...form, [k]: conv(e.target.value) })
  const { password_configurada, ...valoresGuardados } = guardado
  const sucio = JSON.stringify(form) !== JSON.stringify(valoresGuardados) || password || borrarPassword

  async function correr(fn) {
    setMsg(null)
    setOcupado(true)
    try {
      await fn()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }
  const guardar = () => correr(async () => {
    aplicar(await api('/admin/correo/servidor', { method: 'PUT', body: { ...form, smtp_puerto: Number(form.smtp_puerto), smtp_password: password || null, borrar_password: borrarPassword } }))
    setMsg({ ok: true, t: 'Servidor de correo guardado. Lo usan los avisos de todas las sedes.' })
  })
  const enviarPrueba = () => correr(async () => {
    const r = await api('/admin/correo/prueba', { method: 'POST', body: { destinatario: prueba || null } })
    setMsg(r.ok ? { ok: true, t: `Correo de prueba enviado a ${r.destinatarios}.` } : { ok: false, t: r.error })
  })

  return (
    <div className="card">
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><Server size={18} /> Servidor de correo</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Común a todas las sedes: lo usan los avisos a caseta y los correos de prueba. Los destinatarios de caseta los configura el GH de cada sede.
      </p>
      <div className="pol-grid">
        <label className="campo">Método de envío
          <select value={form.metodo} onChange={set('metodo')}>
            <option value="smtp">Servidor SMTP</option>
            <option value="graph">Microsoft 365 (usa la conexión con Microsoft)</option>
          </select>
        </label>
        <label className="campo">Correo remitente
          <input value={form.remitente} onChange={set('remitente')} placeholder="avisos@o-tek.com" />
          <span className="muted" style={{ fontSize: 11 }}>{form.metodo === 'graph' ? 'Buzón de Microsoft 365 (requiere Mail.Send)' : 'Dirección que aparece como remitente'}</span>
        </label>
        <label className="campo">Nombre del remitente<input value={form.remitente_nombre} onChange={set('remitente_nombre')} /></label>
        {form.metodo === 'smtp' && (
          <>
            <label className="campo">Servidor SMTP<input value={form.smtp_host} onChange={set('smtp_host')} placeholder="smtp.office365.com" /></label>
            <label className="campo">Puerto<input type="number" value={form.smtp_puerto} onChange={set('smtp_puerto', Number)} /></label>
            <label className="campo">Seguridad
              <select value={form.smtp_seguridad} onChange={set('smtp_seguridad')}>
                <option value="starttls">STARTTLS (puerto 587)</option>
                <option value="ssl">SSL/TLS (puerto 465)</option>
                <option value="ninguna">Ninguna (servidor interno)</option>
              </select>
            </label>
            <label className="campo">Usuario SMTP<input value={form.smtp_usuario} onChange={set('smtp_usuario')} autoComplete="off" /></label>
            <label className="campo">Contraseña SMTP
              <input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setBorrarPassword(false) }}
                placeholder={password_configurada ? '•••••••• (escribe una nueva para reemplazarla)' : ''} autoComplete="new-password" />
              <span className="muted" style={{ fontSize: 11 }}>{borrarPassword ? 'se eliminará al guardar' : password_configurada ? 'configurada (se guarda cifrada)' : 'sin contraseña'}</span>
            </label>
          </>
        )}
      </div>
      <div className="fila" style={{ marginTop: 12, gap: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-primary" onClick={guardar} disabled={ocupado || !sucio}><Save size={15} /> Guardar</button>
        {password_configurada && !borrarPassword && form.metodo === 'smtp' && (
          <button className="btn btn-sm" onClick={() => { setBorrarPassword(true); setPassword('') }}>Eliminar contraseña</button>
        )}
        <div className="espacio" />
        <input style={{ width: 240 }} value={prueba} onChange={(e) => setPrueba(e.target.value)} placeholder="Correo para la prueba" />
        <button className="btn" onClick={enviarPrueba} disabled={ocupado || sucio || !prueba} title={sucio ? 'Guarda los cambios antes de probar' : ''}><Send size={15} /> Enviar prueba</button>
      </div>
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </div>
  )
}
