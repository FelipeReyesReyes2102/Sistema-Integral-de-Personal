import { useEffect, useState } from 'react'
import { CheckCircle2, Mail, RotateCw, Save, Send, XCircle } from 'lucide-react'
import { api } from '../api'

function Campo({ etiqueta, ayuda, children, full }) {
  return (
    <div className={`of ${full ? 'full' : ''}`}>
      <div className="of-caja"><span className="of-et">{etiqueta}</span>{children}</div>
      {ayuda && <span className="of-ayuda">{ayuda}</span>}
    </div>
  )
}

const EVENTOS = { permiso_autorizado: 'Autorizado', permiso_cancelado: 'Cancelado', prueba: 'Prueba' }

/** Configuración del correo y de los avisos a caseta cuando se autoriza un permiso. */
export default function ConfigCorreo() {
  const [estado, setEstado] = useState(null)
  const [form, setForm] = useState(null)
  const [password, setPassword] = useState('')
  const [borrarPassword, setBorrarPassword] = useState(false)
  const [msg, setMsg] = useState(null)
  const [prueba, setPrueba] = useState('')
  const [historial, setHistorial] = useState([])
  const [ocupado, setOcupado] = useState(false)

  const aplicar = (e) => {
    setEstado(e)
    const { password_configurada, tipos_disponibles, ...valores } = e
    setForm(valores)
    setPassword('')
    setBorrarPassword(false)
  }
  const cargarHistorial = () => api('/admin/correo/historial', { query: { limite: 20 } }).then(setHistorial).catch(() => {})
  useEffect(() => {
    api('/admin/correo').then(aplicar).catch((e) => setMsg({ ok: false, t: e.message }))
    cargarHistorial()
  }, [])

  if (!form) return <div className="card" style={{ marginTop: 24 }}>{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const set = (k, conv = (v) => v) => (e) => setForm({ ...form, [k]: conv(e.target.value) })
  const toggleTipo = (t) => setForm({
    ...form, caseta_tipos: form.caseta_tipos.includes(t) ? form.caseta_tipos.filter((x) => x !== t) : [...form.caseta_tipos, t],
  })
  const { password_configurada, tipos_disponibles, ...guardado } = estado
  const sucio = JSON.stringify(form) !== JSON.stringify(guardado) || password || borrarPassword

  async function guardar() {
    setMsg(null)
    setOcupado(true)
    try {
      aplicar(await api('/admin/correo', {
        method: 'PUT', body: { ...form, smtp_puerto: Number(form.smtp_puerto), smtp_password: password || null, borrar_password: borrarPassword },
      }))
      setMsg({ ok: true, t: 'Configuración guardada. Envía un correo de prueba para verificarla.' })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }

  async function enviarPrueba() {
    setMsg(null)
    setOcupado(true)
    try {
      const r = await api('/admin/correo/prueba', { method: 'POST', body: { destinatario: prueba || null } })
      setMsg(r.ok ? { ok: true, t: `Correo de prueba enviado a ${r.destinatarios}.` } : { ok: false, t: r.error })
      cargarHistorial()
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }

  async function reintentar(n) {
    const r = await api(`/admin/correo/historial/${n.id}/reintentar`, { method: 'POST' }).catch((e) => ({ ok: false, error: e.message }))
    setMsg(r.ok ? { ok: true, t: 'Correo reenviado.' } : { ok: false, t: r.error })
    cargarHistorial()
  }

  return (
    <div className="card" style={{ marginTop: 24 }}>
      <div className="fila" style={{ marginBottom: 6 }}>
        <h3 className="fila" style={{ gap: 8 }}><Mail size={18} /> Avisos por correo a caseta</h3>
        <span className={`pill ${estado.caseta_activo ? 'validado' : 'borrador'}`}>{estado.caseta_activo ? 'Avisos activos' : 'Avisos desactivados'}</span>
      </div>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Cada vez que un jefe o el administrador <b>autoriza</b> un permiso de los tipos seleccionados, se envía un correo al
        personal de caseta con el empleado, número de nómina, fecha y horario. Si después se cancela, también se les avisa.
      </p>

      <div className="cfg-grid">
        <Campo etiqueta="Enviar avisos a caseta">
          <select value={String(form.caseta_activo)} onChange={set('caseta_activo', (v) => v === 'true')}>
            <option value="true">Sí, avisar al autorizar permisos</option>
            <option value="false">No</option>
          </select>
        </Campo>
        <Campo etiqueta="Correos del personal de caseta" ayuda="Separa varios correos con coma">
          <input value={form.caseta_destinatarios} onChange={set('caseta_destinatarios')} placeholder="caseta@o-tek.com, vigilancia@o-tek.com" />
        </Campo>
        <div className="of full">
          <span className="of-ayuda" style={{ fontSize: 12 }}>Permisos que se avisan a caseta:</span>
          <div className="fila">
            {Object.entries(tipos_disponibles).map(([k, v]) => (
              <label key={k} className="checkbox"><input type="checkbox" checked={form.caseta_tipos.includes(k)} onChange={() => toggleTipo(k)} /> {v}</label>
            ))}
          </div>
        </div>

        <Campo etiqueta="Método de envío">
          <select value={form.metodo} onChange={set('metodo')}>
            <option value="smtp">Servidor SMTP</option>
            <option value="graph">Microsoft 365 (usa la conexión con Microsoft)</option>
          </select>
        </Campo>
        <Campo etiqueta="Correo remitente" ayuda={form.metodo === 'graph' ? 'Buzón de Microsoft 365 desde el que se envía (requiere permiso Mail.Send)' : 'Dirección que aparece como remitente'}>
          <input value={form.remitente} onChange={set('remitente')} placeholder="avisos@o-tek.com" />
        </Campo>
        <Campo etiqueta="Nombre del remitente">
          <input value={form.remitente_nombre} onChange={set('remitente_nombre')} />
        </Campo>

        {form.metodo === 'smtp' && (
          <>
            <Campo etiqueta="Servidor SMTP" ayuda="Ej. smtp.office365.com o el de su proveedor">
              <input value={form.smtp_host} onChange={set('smtp_host')} placeholder="smtp.office365.com" />
            </Campo>
            <Campo etiqueta="Puerto">
              <input type="number" value={form.smtp_puerto} onChange={set('smtp_puerto', Number)} />
            </Campo>
            <Campo etiqueta="Seguridad">
              <select value={form.smtp_seguridad} onChange={set('smtp_seguridad')}>
                <option value="starttls">STARTTLS (puerto 587)</option>
                <option value="ssl">SSL/TLS (puerto 465)</option>
                <option value="ninguna">Ninguna (servidor interno)</option>
              </select>
            </Campo>
            <Campo etiqueta="Usuario SMTP" ayuda="Vacío si el servidor no pide autenticación">
              <input value={form.smtp_usuario} onChange={set('smtp_usuario')} autoComplete="off" />
            </Campo>
            <Campo etiqueta="Contraseña SMTP"
              ayuda={borrarPassword ? 'se eliminará al guardar' : password_configurada ? 'contraseña configurada (se guarda cifrada)' : 'sin contraseña'}>
              <input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setBorrarPassword(false) }}
                placeholder={password_configurada ? '•••••••• (escribe una nueva para reemplazarla)' : ''} autoComplete="new-password" />
            </Campo>
          </>
        )}
      </div>

      <div className="fila" style={{ marginTop: 16 }}>
        <button className="btn btn-primary" onClick={guardar} disabled={ocupado || !sucio}><Save size={15} /> Guardar</button>
        {password_configurada && !borrarPassword && form.metodo === 'smtp' && (
          <button className="btn btn-sm" onClick={() => { setBorrarPassword(true); setPassword('') }}>Eliminar contraseña</button>
        )}
        <div className="espacio" />
        <input style={{ width: 240 }} value={prueba} onChange={(e) => setPrueba(e.target.value)} placeholder="Correo para la prueba (opcional)" />
        <button className="btn" onClick={enviarPrueba} disabled={ocupado || sucio} title={sucio ? 'Guarda los cambios antes de probar' : ''}>
          <Send size={15} /> Enviar correo de prueba
        </button>
      </div>
      {sucio && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Hay cambios sin guardar.</div>}
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}

      <h4 style={{ margin: '20px 0 8px', fontSize: 14 }}>Últimos envíos</h4>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Fecha</th><th>Aviso</th><th>Empleado</th><th>Destinatarios</th><th>Estado</th><th /></tr></thead>
          <tbody>
            {historial.length === 0 && <tr><td colSpan={6} className="muted" style={{ textAlign: 'center' }}>Aún no se han enviado correos.</td></tr>}
            {historial.map((n) => (
              <tr key={n.id}>
                <td style={{ whiteSpace: 'nowrap' }}>{n.fecha?.slice(0, 16).replace('T', ' ')}</td>
                <td>{EVENTOS[n.evento] || n.evento}{n.tipo ? ` · ${n.tipo}` : ''}</td>
                <td>{n.empleado || '—'}</td>
                <td className="muted" style={{ fontSize: 12 }}>{n.destinatarios}</td>
                <td>
                  {n.estado === 'enviado'
                    ? <span className="fila" style={{ gap: 4, color: '#2e7d32' }}><CheckCircle2 size={15} /> Enviado</span>
                    : <span className="fila" style={{ gap: 4, color: 'var(--danger)', alignItems: 'flex-start' }} title={n.error}>
                        <XCircle size={15} /> {n.estado === 'error' ? n.error : 'Pendiente'}
                      </span>}
                </td>
                <td>{n.estado !== 'enviado' && <button className="btn btn-sm" onClick={() => reintentar(n)}><RotateCw size={13} /> Reintentar</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
