import { useEffect, useState } from 'react'
import { Award, Cake, Check, Send, UserMinus, X } from 'lucide-react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import BuscadorPaciente from '../components/BuscadorPaciente'

const ESTADO = { pendiente: 'Esperando respuesta', aceptada: 'Lo ves en tu calendario', rechazada: 'No aceptó' }

function Persona({ p, children, nota }) {
  return (
    <div className="est-fila">
      <Avatar usuario={p} tam={36} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <b>{p.nombre}</b>
        <div className="muted" style={{ fontSize: 12 }}>{[p.puesto, p.departamento, p.sede_nombre].filter(Boolean).join(' · ')}</div>
        {nota}
      </div>
      <div className="fila" style={{ gap: 6, flexWrap: 'nowrap' }}>{children}</div>
    </div>
  )
}

/** Cumpleaños y aniversarios: preferencias, solicitudes y quién ve los míos. */
export default function Estimados() {
  const [datos, setDatos] = useState(null)
  const [elegida, setElegida] = useState(null)
  const [msg, setMsg] = useState(null)
  const cargar = () => api('/estimados').then(setDatos).catch((e) => setMsg({ ok: false, t: e.message }))
  useEffect(() => { cargar() }, [])

  async function hacer(ruta, metodo = 'POST', body, texto) {
    setMsg(null)
    try {
      await api(ruta, { method: metodo, body })
      if (texto) setMsg({ ok: true, t: texto })
      cargar()
      window.dispatchEvent(new Event('pendientes:refrescar'))
    } catch (e) {
      setMsg({ ok: false, t: e.message })
    }
  }

  async function preferencia(k, v) {
    const p = { ...datos.preferencias, [k]: v }
    setDatos({ ...datos, preferencias: p })
    await hacer('/estimados/preferencias', 'PUT', p)
  }

  if (!datos) return <div className="card">{msg ? <div className="alerta error">{msg.t}</div> : 'Cargando…'}</div>
  const pref = datos.preferencias
  return (
    <div className="estimados">
      <div className="card">
        <b style={{ fontSize: 16 }}>Cumpleaños y aniversarios en tu calendario</b>
        <p className="muted" style={{ margin: '4px 0 10px', fontSize: 13 }}>
          Tu cumpleaños y tu aniversario en la empresa solo los ven las personas a las que tú autorizas. Para ver los de un compañero,
          envíale una solicitud: si la acepta, aparecen en tu calendario.
        </p>
        <div className="fila" style={{ gap: 24 }}>
          <label className="checkbox"><input type="checkbox" checked={pref.ver_cumpleanos} onChange={(e) => preferencia('ver_cumpleanos', e.target.checked)} />
            <Cake size={15} /> Ver cumpleaños de las personas que me autorizaron</label>
          <label className="checkbox"><input type="checkbox" checked={pref.ver_aniversarios} onChange={(e) => preferencia('ver_aniversarios', e.target.checked)} />
            <Award size={15} /> Ver sus aniversarios en la empresa</label>
        </div>
        {msg && <div className={`alerta ${msg.ok ? 'ok' : 'error'}`} style={{ marginTop: 10 }}>{msg.t}</div>}
      </div>

      {datos.recibidas.length > 0 && (
        <div className="card est-recibidas">
          <b>Te pidieron ver tu cumpleaños y aniversario ({datos.recibidas.length})</b>
          {datos.recibidas.map((c) => (
            <Persona key={c.id} p={c.persona}>
              <button className="btn btn-sm btn-success" onClick={() => hacer(`/estimados/${c.id}/aceptar`, 'POST', null, `${c.persona.nombre} ya puede ver tu cumpleaños y aniversario.`)}><Check size={14} /> Aceptar</button>
              <button className="btn btn-sm" onClick={() => hacer(`/estimados/${c.id}/rechazar`)}><X size={14} /> No aceptar</button>
            </Persona>
          ))}
        </div>
      )}

      <div className="card">
        <b>Pedir ver los de un compañero</b>
        <div style={{ marginTop: 8 }}>
          <BuscadorPaciente value={elegida} onChange={setElegida} endpoint="/estimados/buscar" placeholder="Nombre, apellido o nómina…"
            extra={(p) => (p.estado ? ESTADO[p.estado] : 'Aún no le has enviado solicitud')} />
        </div>
        {elegida && (
          <div className="fila" style={{ marginTop: 10, justifyContent: 'flex-end' }}>
            <button className="btn btn-primary" disabled={elegida.estado === 'aceptada' || elegida.estado === 'pendiente'}
              onClick={async () => { await hacer('/estimados', 'POST', { persona_id: elegida.id }, `Solicitud enviada a ${elegida.nombre}.`); setElegida(null) }}>
              <Send size={15} /> Enviar solicitud
            </button>
          </div>
        )}
      </div>

      <div className="card">
        <b>Personas que veo ({datos.veo.filter((c) => c.estado === 'aceptada').length})</b>
        {datos.veo.length === 0 && <div className="muted" style={{ padding: '10px 0' }}>Aún no has pedido ver los de nadie.</div>}
        {datos.veo.map((c) => (
          <Persona key={c.id} p={c.persona} nota={<span className={`pill ${c.estado === 'aceptada' ? 'validado' : c.estado === 'pendiente' ? 'solicitado' : 'rechazado'}`}>{ESTADO[c.estado]}</span>}>
            {c.estado === 'rechazada' && <button className="btn btn-sm" onClick={() => hacer('/estimados', 'POST', { persona_id: c.persona.id }, `Solicitud enviada otra vez a ${c.persona.nombre}.`)}><Send size={14} /> Volver a pedir</button>}
            <button className="btn btn-sm" title={c.estado === 'aceptada' ? 'Dejar de ver' : 'Cancelar solicitud'}
              onClick={() => hacer(`/estimados/${c.id}`, 'DELETE')}><X size={14} /> {c.estado === 'aceptada' ? 'Dejar de ver' : 'Quitar'}</button>
          </Persona>
        ))}
      </div>

      <div className="card">
        <b>Quién ve los míos ({datos.me_ven.length})</b>
        {datos.me_ven.length === 0 && <div className="muted" style={{ padding: '10px 0' }}>Nadie ve tu cumpleaños ni tu aniversario.</div>}
        {datos.me_ven.map((c) => (
          <Persona key={c.id} p={c.persona}>
            <button className="btn btn-sm btn-danger" onClick={() => hacer(`/estimados/${c.id}`, 'DELETE', null, `${c.persona.nombre} ya no ve tu cumpleaños ni tu aniversario.`)}><UserMinus size={14} /> Quitar acceso</button>
          </Persona>
        ))}
      </div>
    </div>
  )
}
