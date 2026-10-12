import { useEffect, useState } from 'react'
import { CheckCircle2, CircleAlert, CircleMinus, Copy, PlugZap, RotateCcw, Save, XCircle } from 'lucide-react'
import { api } from '../api'

const ORIGEN = { configuracion: 'guardado en la aplicación', env: 'desde .env' }

function Campo({ etiqueta, variable, origen, ayuda, children, full }) {
  return (
    <div className={`of ${full ? 'full' : ''}`}>
      <div className="of-caja">
        <span className="of-et">{etiqueta}</span>
        {children}
      </div>
      <span className="of-ayuda">{variable}{origen ? ` · ${ORIGEN[origen]}` : ''}{ayuda ? ` · ${ayuda}` : ''}</span>
    </div>
  )
}

/** Configuración de la conexión con Microsoft Entra ID (solo administrador). */
export default function ConfigMicrosoft() {
  const [estado, setEstado] = useState(null)
  const [form, setForm] = useState(null)
  const [secreto, setSecreto] = useState('')
  const [borrarSecreto, setBorrarSecreto] = useState(false)
  const [msg, setMsg] = useState(null)
  const [pruebas, setPruebas] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  const aplicar = (e) => {
    setEstado(e)
    setForm(e.valores)
    setSecreto('')
    setBorrarSecreto(false)
  }
  useEffect(() => { api('/admin/config/microsoft').then(aplicar).catch((e) => setMsg({ ok: false, t: e.message })) }, [])

  if (!form) return <div className="card" style={{ marginTop: 24 }}>{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>

  const set = (k, conv = (v) => v) => (e) => setForm({ ...form, [k]: conv(e.target.value) })
  const sucio = JSON.stringify(form) !== JSON.stringify(estado.valores) || secreto || borrarSecreto
  const redirectSugerida = form.microsoft_frontend_url ? `${form.microsoft_frontend_url.replace(/\/$/, '')}/api/auth/microsoft/callback` : ''

  async function guardar() {
    setMsg(null)
    setPruebas(null)
    setOcupado(true)
    try {
      const r = await api('/admin/config/microsoft', {
        method: 'PUT', body: { ...form, microsoft_client_secret: secreto || null, borrar_secreto: borrarSecreto },
      })
      aplicar(r)
      setMsg({ ok: true, t: 'Configuración guardada. Usa "Probar conexión" para verificarla.' })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }

  async function probar() {
    setMsg(null)
    setOcupado(true)
    try {
      setPruebas((await api('/admin/config/microsoft/probar', { method: 'POST' })).resultados)
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado(false)
    }
  }

  async function restaurar() {
    if (!window.confirm('¿Borrar lo guardado aquí y volver a usar los valores del archivo .env del servidor?')) return
    try {
      aplicar(await api('/admin/config/microsoft', { method: 'DELETE' }))
      setMsg({ ok: true, t: 'Se restauraron los valores de .env.' })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  const copiar = (t) => navigator.clipboard?.writeText(t)
  const icono = { ok: <CheckCircle2 size={16} color="#2e7d32" />, error: <XCircle size={16} color="#c62828" />, aviso: <CircleAlert size={16} color="#a07000" />, omitido: <CircleMinus size={16} color="#888" /> }

  return (
    <div className="card" style={{ marginTop: 24 }}>
      <div className="fila" style={{ marginBottom: 6 }}>
        <h3>Conexión con Microsoft</h3>
        <span className={`pill ${estado.microsoft_login_configurado ? 'validado' : 'borrador'}`}>
          {estado.microsoft_login_configurado ? 'Inicio de sesión activo' : 'Inicio de sesión inactivo'}
        </span>
        <span className={`pill ${estado.microsoft_graph_configurado ? 'validado' : 'borrador'}`}>
          {estado.microsoft_graph_configurado ? 'Consulta de empleados activa' : 'Consulta de empleados inactiva'}
        </span>
      </div>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Los valores guardados aquí tienen prioridad sobre el archivo <code>.env</code> del servidor. El secreto se guarda cifrado y no se vuelve a mostrar.
      </p>

      <div className="cfg-grid">
        <Campo etiqueta="Autenticación Microsoft habilitada" variable="MICROSOFT_AUTH_ENABLED" origen={estado.origen.MICROSOFT_AUTH_ENABLED}>
          <select value={String(form.microsoft_auth_enabled)} onChange={set('microsoft_auth_enabled', (v) => v === 'true')}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </Campo>
        <Campo etiqueta="Id. del directorio (tenant)" variable="MICROSOFT_TENANT_ID" origen={estado.origen.MICROSOFT_TENANT_ID}>
          <input value={form.microsoft_tenant_id} onChange={set('microsoft_tenant_id')} placeholder="00000000-0000-0000-0000-000000000000" spellCheck={false} />
        </Campo>
        <Campo etiqueta="Id. de aplicación (cliente)" variable="MICROSOFT_CLIENT_ID" origen={estado.origen.MICROSOFT_CLIENT_ID}>
          <input value={form.microsoft_client_id} onChange={set('microsoft_client_id')} placeholder="00000000-0000-0000-0000-000000000000" spellCheck={false} />
        </Campo>
        <Campo etiqueta="Secreto de cliente" variable="MICROSOFT_CLIENT_SECRET"
          ayuda={borrarSecreto ? 'se eliminará al guardar' : estado.secreto_configurado ? 'secreto configurado' : 'sin secreto'}>
          <input type="password" value={secreto} onChange={(e) => { setSecreto(e.target.value); setBorrarSecreto(false) }}
            placeholder={estado.secreto_configurado ? '•••••••• (escribe uno nuevo para reemplazarlo)' : 'Secreto de cliente'}
            autoComplete="new-password" />
        </Campo>
        <Campo etiqueta="URI de redirección" variable="MICROSOFT_REDIRECT_URI" origen={estado.origen.MICROSOFT_REDIRECT_URI}>
          <input value={form.microsoft_redirect_uri} onChange={set('microsoft_redirect_uri')} spellCheck={false}
            placeholder="https://<dominio>/api/auth/microsoft/callback" />
        </Campo>
        <Campo etiqueta="URL pública del frontend" variable="MICROSOFT_FRONTEND_URL" origen={estado.origen.MICROSOFT_FRONTEND_URL}>
          <input value={form.microsoft_frontend_url} onChange={set('microsoft_frontend_url')} spellCheck={false} placeholder="https://<dominio>" />
        </Campo>
        <Campo etiqueta="Permisos solicitados (scopes)" variable="MICROSOFT_SCOPES" origen={estado.origen.MICROSOFT_SCOPES}>
          <input value={form.microsoft_scopes} onChange={set('microsoft_scopes')} spellCheck={false} />
        </Campo>
        <Campo etiqueta="Consulta de empleados en Microsoft Graph" variable="MICROSOFT_GRAPH_ENABLED" origen={estado.origen.MICROSOFT_GRAPH_ENABLED}
          ayuda="requiere User.Read.All">
          <select value={String(form.microsoft_graph_enabled)} onChange={set('microsoft_graph_enabled', (v) => v === 'true')}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </Campo>
        <Campo etiqueta="Acceso con usuario y contraseña" variable="PASSWORD_LOGIN_ENABLED" origen={estado.origen.PASSWORD_LOGIN_ENABLED}>
          <select value={String(form.password_login_enabled)} onChange={set('password_login_enabled', (v) => v === 'true')}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </Campo>
        <Campo etiqueta="Roles que pueden usar contraseña" variable="PASSWORD_LOGIN_ROLES" origen={estado.origen.PASSWORD_LOGIN_ROLES}
          ayuda="vacío = todos; ej. planta">
          <input value={form.password_login_roles} onChange={set('password_login_roles')} placeholder="planta" spellCheck={false} />
        </Campo>
      </div>

      <div className="cfg-info">
        <b>Datos para registrar la app en Microsoft Entra ID</b>
        <ul>
          <li>Plataforma <b>Web</b>, URI de redirección:{' '}
            <code>{form.microsoft_redirect_uri || redirectSugerida || '—'}</code>
            {(form.microsoft_redirect_uri || redirectSugerida) && (
              <button className="icon-btn plain" title="Copiar" onClick={() => copiar(form.microsoft_redirect_uri || redirectSugerida)}><Copy size={14} /></button>
            )}
            {redirectSugerida && redirectSugerida !== form.microsoft_redirect_uri && (
              <button className="btn btn-sm" style={{ marginLeft: 6 }} onClick={() => setForm({ ...form, microsoft_redirect_uri: redirectSugerida })}>
                Usar {redirectSugerida}
              </button>
            )}
          </li>
          <li>Permisos delegados: <code>openid profile email User.Read</code>. Permiso de aplicación <code>User.Read.All</code> con consentimiento de administrador (para cargar datos y fotos).</li>
          <li>Guía completa: <code>docs/MICROSOFT_ENTRA.md</code></li>
        </ul>
      </div>

      <div className="fila" style={{ marginTop: 14 }}>
        <button className="btn btn-primary" onClick={guardar} disabled={ocupado || !sucio}><Save size={15} /> Guardar</button>
        <button className="btn" onClick={probar} disabled={ocupado || sucio} title={sucio ? 'Guarda los cambios antes de probar' : ''}>
          <PlugZap size={15} /> Probar conexión
        </button>
        {estado.secreto_configurado && !borrarSecreto && (
          <button className="btn btn-sm" onClick={() => { setBorrarSecreto(true); setSecreto('') }}>Eliminar secreto</button>
        )}
        <div className="espacio" />
        <button className="btn btn-sm" onClick={restaurar}><RotateCcw size={14} /> Volver a valores de .env</button>
      </div>
      {sucio && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Hay cambios sin guardar.</div>}
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
      {pruebas && (
        <div className="cfg-pruebas">
          {pruebas.map((p) => (
            <div key={p.nombre} className="fila" style={{ gap: 8, flexWrap: 'nowrap', alignItems: 'flex-start' }}>
              {icono[p.estado]}
              <div><b>{p.nombre}:</b> {p.detalle}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
