import { useEffect, useState } from 'react'
import { CalendarCheck, Clock, ExternalLink, Link2, MessageSquareMore, RefreshCw, Save, Send, Share2, Unlink } from 'lucide-react'
import { api } from '../api'
import { fmtFecha } from '../utils'

const TITULOS = { vacaciones: { t: 'Vacaciones', i: CalendarCheck }, permisos: { t: 'Permisos y home office', i: Clock } }
const TIPOS_COL = { text: 'Texto', number: 'Número', currency: 'Moneda', dateTime: 'Fecha', choice: 'Opción', boolean: 'Sí/No',
  personOrGroup: 'Persona', lookup: 'Búsqueda', calculated: 'Calculada', hyperlinkOrPicture: 'Hipervínculo', term: 'Metadatos' }

function Lista({ datos, onCambio }) {
  const [url, setUrl] = useState(datos.url || '')
  const [mapeo, setMapeo] = useState(datos.mapeo || {})
  const [valores, setValores] = useState(datos.valores || {})
  const [activo, setActivo] = useState(!!datos.activo)
  const [teams, setTeams] = useState(datos.teams || {})
  const [desde, setDesde] = useState(`${new Date().getFullYear()}-01-01`)
  const [msg, setMsg] = useState(null)
  const [ocupado, setOcupado] = useState('')

  useEffect(() => {
    setUrl(datos.url || ''); setMapeo(datos.mapeo || {}); setValores(datos.valores || {}); setActivo(!!datos.activo)
    setTeams(datos.teams || {})
  }, [datos])

  const campos = Object.fromEntries(datos.campos.map((c) => [c.clave, c]))
  const tipo = datos.tipo
  const correr = async (clave, fn, ok) => {
    setOcupado(clave)
    setMsg(null)
    try {
      const r = await fn()
      onCambio(tipo, r)
      if (ok) setMsg({ ok: true, t: typeof ok === 'function' ? ok(r) : ok })
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    } finally {
      setOcupado('')
    }
  }
  const conectar = () => correr('conectar', () => api(`/sharepoint/${tipo}/conectar`, { method: 'PUT', body: { url } }),
    'Lista conectada. Revisa qué dato va en cada columna, activa el envío y guarda.')
  const guardar = () => correr('guardar', () => api(`/sharepoint/${tipo}`, { method: 'PUT', body: {
    activo, mapeo, valores, aprobacion_teams: !!teams.activo, col_decision: teams.col_decision || null,
    val_aprobado: teams.val_aprobado, val_rechazado: teams.val_rechazado, col_comentario: teams.col_comentario || null,
    col_respondio: teams.col_respondio || null, cuenta_flujo: teams.cuenta_flujo || null } }),
    activo ? 'Guardado. Las solicitudes se enviarán a la lista al enviarse y se actualizarán con cada cambio.' : 'Guardado (envío desactivado).')
  const existentes = () => correr('existentes', () => api(`/sharepoint/${tipo}/existentes`, { method: 'POST', body: { desde } }),
    (r) => (r.encolados ? `${r.encolados} solicitud(es) en cola; se envían en segundo plano.` : 'No hay solicitudes nuevas que enviar desde esa fecha.'))
  const reintentar = () => correr('reintentar', () => api(`/sharepoint/${tipo}/reintentar`, { method: 'POST' }), 'Reintentando en segundo plano…')
  const actualizar = () => correr('actualizar', () => api('/sharepoint').then((r) => r.listas[tipo]))
  const desconectar = () => {
    if (!window.confirm('¿Dejar de enviar a esta lista? No se borra nada en SharePoint.')) return
    correr('desconectar', () => api(`/sharepoint/${tipo}`, { method: 'DELETE' }), 'Lista desconectada.')
  }

  const usados = new Set(Object.values(mapeo).filter(Boolean))
  const T = TITULOS[tipo]
  return (
    <div className="sp-lista">
      <div className="fila" style={{ gap: 8 }}>
        <T.i size={17} color="var(--primary)" /><b>{T.t}</b>
        {datos.conectada && <span className={`chip ${datos.activo ? 'sp-on' : ''}`}>{datos.activo ? 'Enviando' : 'Envío desactivado'}</span>}
      </div>
      <div className="sp-url">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://<empresa>.sharepoint.com/sites/<sitio>/Lists/<lista>/AllItems.aspx" />
        <button className="btn btn-sm" onClick={conectar} disabled={!url.trim() || !!ocupado}>
          <Link2 size={14} /> {ocupado === 'conectar' ? 'Conectando…' : datos.conectada ? 'Volver a leer columnas' : 'Conectar'}
        </button>
      </div>

      {datos.conectada && (
        <>
          <div className="sp-info">
            Lista <b>{datos.lista_nombre}</b> del sitio <b>{datos.sitio_nombre}</b>
            {' '}<a href={datos.url} target="_blank" rel="noreferrer"><ExternalLink size={12} /> abrir</a>
            <span className="espacio" />
            <span className="sp-cuenta ok">{datos.cuentas.enviado} enviadas</span>
            {datos.cuentas.pendiente > 0 && <span className="sp-cuenta">{datos.cuentas.pendiente} en cola</span>}
            {datos.cuentas.error > 0 && <span className="sp-cuenta error">{datos.cuentas.error} con error</span>}
            <button className="icon-btn plain" title="Actualizar" onClick={actualizar}><RefreshCw size={13} /></button>
          </div>

          <table className="tabla sp-mapeo">
            <thead><tr><th>Columna de la lista</th><th>Dato de SIP-O que se guarda</th></tr></thead>
            <tbody>
              {datos.columnas.map((c) => {
                const campo = campos[mapeo[c.nombre]]
                const conOpciones = campo?.valores && c.tipo === 'choice'
                return (
                  <tr key={c.nombre}>
                    <td>
                      <b>{c.titulo}</b>{c.requerida && <span className="rojo" title="Obligatoria"> *</span>}
                      <div className="muted" style={{ fontSize: 11 }}>{TIPOS_COL[c.tipo] || c.tipo}{c.titulo !== c.nombre ? ` · ${c.nombre}` : ''}</div>
                    </td>
                    <td>
                      {c.compatible ? (
                        <select value={mapeo[c.nombre] || ''} onChange={(e) => setMapeo({ ...mapeo, [c.nombre]: e.target.value })}>
                          <option value="">— No enviar —</option>
                          {datos.campos.map((f) => (
                            <option key={f.clave} value={f.clave} disabled={usados.has(f.clave) && mapeo[c.nombre] !== f.clave}>{f.etiqueta}</option>
                          ))}
                        </select>
                      ) : <span className="muted" style={{ fontSize: 12 }}>No se puede llenar desde SIP-O (columna de tipo {TIPOS_COL[c.tipo] || c.tipo}); usa una de texto.</span>}
                      {conOpciones && (
                        <div className="sp-opciones">
                          {Object.entries(campo.valores).map(([k, etiqueta]) => (
                            <label key={k}>
                              <span>{etiqueta}</span>
                              <select value={valores[c.nombre]?.[k] || ''}
                                onChange={(e) => setValores({ ...valores, [c.nombre]: { ...(valores[c.nombre] || {}), [k]: e.target.value } })}>
                                <option value="">{c.texto_libre ? `«${etiqueta}»` : '— elige —'}</option>
                                {c.opciones.map((o) => <option key={o} value={o}>{o}</option>)}
                              </select>
                            </label>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          <div className="fila" style={{ marginTop: 10, gap: 8, flexWrap: 'wrap' }}>
            <label className="checkbox"><input type="checkbox" checked={activo} onChange={(e) => setActivo(e.target.checked)} /> Enviar las solicitudes de esta sede a la lista</label>
            <div className="espacio" />
            <button className="btn btn-sm" onClick={desconectar} disabled={!!ocupado}><Unlink size={14} /> Desconectar</button>
            <button className="btn btn-primary btn-sm" onClick={guardar} disabled={!!ocupado}><Save size={14} /> Guardar</button>
          </div>

          <AprobacionTeams datos={datos} teams={teams} setTeams={setTeams} mapeo={mapeo} valores={valores} />

          {datos.activo && (
            <div className="sp-existentes">
              <span>Enviar también las solicitudes que ya existen desde</span>
              <input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
              <button className="btn btn-sm" onClick={existentes} disabled={!desde || !!ocupado}><Send size={14} /> Enviar historial</button>
              <span className="muted" style={{ fontSize: 11 }}>Las que ya se enviaron no se duplican.</span>
            </div>
          )}

          {datos.errores?.length > 0 && (
            <div className="sp-errores">
              <div className="fila"><b>Últimos errores</b><div className="espacio" />
                <button className="btn btn-sm" onClick={reintentar} disabled={!!ocupado}><RefreshCw size={14} /> Reintentar ahora</button></div>
              {datos.errores.map((e) => (
                <div key={e.folio} className="sp-error"><b>{e.folio}</b> · {fmtFecha(e.fecha)} · {e.intentos} intento(s)<div>{e.error}</div></div>
              ))}
            </div>
          )}
        </>
      )}
      {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`}>{msg.t}</div>}
    </div>
  )
}

/** Aprobación desde Teams: Power Automate pide la aprobación al jefe y escribe la decisión en la lista; SIP-O la aplica. */
function AprobacionTeams({ datos, teams, setTeams, mapeo, valores }) {
  const set = (k) => (e) => setTeams({ ...teams, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const libres = datos.columnas.filter((c) => ['text', 'choice'].includes(c.tipo) && !mapeo[c.nombre])
  const titulo = (n) => datos.columnas.find((c) => c.nombre === n)?.titulo || n
  const colDe = (campo) => Object.entries(mapeo).find(([, v]) => v === campo)?.[0]
  const colEstado = colDe('estado')
  const pendiente = (colEstado && valores[colEstado]?.solicitado) || 'Solicitado'
  const selCol = (k, opcional) => (
    <select value={teams[k] || ''} onChange={set(k)}>
      <option value="">{opcional ? '— No usar —' : '— Elige una columna —'}</option>
      {libres.map((c) => <option key={c.nombre} value={c.nombre}>{c.titulo}</option>)}
    </select>
  )
  const nombre = datos.tipo === 'vacaciones' ? 'Vacaciones' : 'Permiso'
  return (
    <div className="sp-teams">
      <label className="checkbox"><input type="checkbox" checked={!!teams.activo} onChange={set('activo')} />
        <MessageSquareMore size={15} /> <b>El jefe aprueba o rechaza desde Teams</b> (con un flujo de Power Automate)</label>
      {teams.activo && (
        <>
          <p className="muted" style={{ fontSize: 12, margin: '6px 0 8px' }}>
            El flujo pide la aprobación en Teams (y Outlook) al <b>correo del jefe</b> y escribe la respuesta en la lista. SIP-O la lee
            cada minuto, la aplica como si el jefe la hubiera aprobado en la aplicación y la registra en la bitácora. También se puede seguir
            aprobando desde SIP-O; si se resuelve primero aquí, la respuesta de Teams se ignora.
          </p>
          <div className="sp-teams-grid">
            <label className="campo">Columna donde el flujo escribe la decisión *{selCol('col_decision')}</label>
            <label className="campo">Valor de aprobado<input value={teams.val_aprobado || ''} onChange={set('val_aprobado')} placeholder="Approve" /></label>
            <label className="campo">Valor de rechazado<input value={teams.val_rechazado || ''} onChange={set('val_rechazado')} placeholder="Reject" /></label>
            <label className="campo">Columna de comentarios del jefe{selCol('col_comentario', true)}</label>
            <label className="campo">Columna de quién respondió (correo) — recomendada{selCol('col_respondio', true)}</label>
            <label className="campo">Cuenta con la que corre el flujo — recomendada
              <input type="email" value={teams.cuenta_flujo || ''} onChange={set('cuenta_flujo')} placeholder="flujos@o-tek.com" />
            </label>
          </div>
          <p className="muted" style={{ fontSize: 11, margin: '4px 0 0' }}>
            Por seguridad, SIP-O solo acepta la decisión si la escribió la cuenta del flujo y si quien respondió es el jefe aprobador
            (o GH de la sede). Da permiso de edición de la lista solo a esa cuenta y a GH.
          </p>
          {!libres.length && <div className="alerta error">Crea en la lista columnas de texto para la decisión, los comentarios y quién respondió.</div>}
          {datos.notas_teams?.length > 0 && (
            <div className="sp-errores">
              <b>Decisiones de Teams no aplicadas</b>
              {datos.notas_teams.map((n) => <div key={n.folio} className="sp-error"><b>{n.folio}</b><div>{n.nota}</div></div>)}
            </div>
          )}
          <details className="sp-guia">
            <summary>Cómo crear el flujo en Power Automate (paso a paso)</summary>
            <ol>
              <li>En la lista <b>{datos.lista_nombre}</b> crea columnas de <i>una línea de texto</i> para la decisión, los comentarios y
                quién respondió (p. ej. «Decisión Teams», «Comentario Teams», «Respondió») y elígelas arriba. Asegúrate de que SIP-O
                envíe <b>Correo del jefe / aprobador</b> y <b>Estado</b> a alguna columna.</li>
              <li>En <b>make.powerautomate.com</b>: Crear → <i>Flujo de nube automatizado</i> → disparador de SharePoint
                <b> «Cuando se crea un elemento»</b>, con el sitio <b>{datos.sitio_nombre}</b> y la lista <b>{datos.lista_nombre}</b>.</li>
              <li>Agrega una <b>Condición</b>: <i>{colEstado ? titulo(colEstado) : 'Estado'}</i> es igual a <b>{pendiente}</b>
                (así no se piden aprobaciones del historial ya resuelto). Lo siguiente va en la rama <i>Sí</i>.</li>
              <li>Acción <b>Aprobaciones → «Iniciar y esperar una aprobación»</b>: tipo <i>Aprobar/Rechazar: primero en responder</i>;
                Título <i>{nombre} · {titulo(colDe('empleado') || 'Empleado')} · {titulo(colDe('folio') || 'Title')}</i>; Asignado a: la
                columna <b>{colDe('correo_jefe') ? titulo(colDe('correo_jefe')) : 'Correo del jefe'}</b>; en Detalles pon las fechas y los
                días; Vínculo del elemento: <i>https://sip-o.otek.internal/</i> con el texto «Abrir SIP-O».</li>
              <li>Acción <b>SharePoint → «Actualizar elemento»</b> (mismo sitio, lista e <i>Id</i> del disparador):
                {' '}<b>{teams.col_decision ? titulo(teams.col_decision) : 'Decisión'}</b> = <i>Resultado</i> (Outcome)
                {teams.col_comentario && <>; <b>{titulo(teams.col_comentario)}</b> = <i>Respuestas Comentarios</i></>}
                {teams.col_respondio && <>; <b>{titulo(teams.col_respondio)}</b> = <i>Respuestas Correo electrónico del aprobador</i></>}.
                Si pide Título, usa el Título del disparador. Power Automate puede envolverlo en «Aplicar a cada uno»: es normal.</li>
              <li>Guarda y prueba con una solicitud real. La cuenta de la conexión de SharePoint del flujo es la <b>cuenta del flujo</b> de arriba.
                El resultado llega en inglés (<i>Approve</i>/<i>Reject</i>); si lo traduces, cambia aquí los valores.</li>
            </ol>
            <p className="muted" style={{ fontSize: 11 }}>Una aprobación de Power Automate espera hasta 30 días; si vence, la solicitud sigue pendiente en SIP-O.</p>
          </details>
        </>
      )}
    </div>
  )
}

/** Listas de SharePoint donde se registran las solicitudes de vacaciones y permisos de la sede activa. */
export default function ConfigSharePoint() {
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { api('/sharepoint').then(setD).catch((e) => setError(e.message)) }, [])
  if (!d) return <div className="card">{error ? <div className="alerta error">{error}</div> : 'Cargando…'}</div>
  const cambiar = (tipo, r) => setD({ ...d, listas: { ...d.listas, [tipo]: r } })
  return (
    <div className="card">
      <h3 className="fila" style={{ gap: 8, marginBottom: 6 }}><Share2 size={18} /> Listas de SharePoint · {d.sede_nombre}</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        Pega la URL de la lista donde se registran las solicitudes. Cada solicitud se agrega a la lista cuando se envía y el
        mismo elemento se actualiza al validarse, rechazarse o cancelarse. Los borradores no se envían. Requiere el permiso de
        aplicación <b>Sites.ReadWrite.All</b> (o Sites.Selected con acceso al sitio) en la app de Microsoft.
      </p>
      {Object.keys(TITULOS).map((t) => <Lista key={t} datos={d.listas[t]} onCambio={cambiar} />)}
    </div>
  )
}
