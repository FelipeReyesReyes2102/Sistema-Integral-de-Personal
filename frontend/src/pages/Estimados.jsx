import { useEffect, useState } from 'react'
import { Award, Cake } from 'lucide-react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import { fmtFecha } from '../utils'

/** Cumpleaños y aniversarios del personal de la sede: preferencias del calendario y próximos. */
export default function Estimados() {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState('')
  const cargar = () => api('/estimados').then(setDatos).catch((e) => setError(e.message))
  useEffect(() => { cargar() }, [])

  async function preferencia(k, v) {
    const p = { ...datos.preferencias, [k]: v }
    setDatos({ ...datos, preferencias: p })
    setError('')
    try {
      await api('/estimados/preferencias', { method: 'PUT', body: p })
      cargar()
    } catch (e) {
      setError(e.message)
    }
  }

  if (!datos) return <div className="card">{error ? <div className="alerta error">{error}</div> : 'Cargando…'}</div>
  const pref = datos.preferencias
  return (
    <div className="estimados">
      <div className="card">
        <p className="muted" style={{ margin: '0 0 10px', fontSize: 13 }}>
          Los cumpleaños y aniversarios del personal de tu sede aparecen en tu calendario. Si no quieres verlos, desmárcalos.
          Tu cumpleaños y tu aniversario siempre los ves.
        </p>
        <div className="fila" style={{ gap: 24 }}>
          <label className="checkbox"><input type="checkbox" checked={pref.ver_cumpleanos} onChange={(e) => preferencia('ver_cumpleanos', e.target.checked)} />
            <Cake size={15} /> Ver cumpleaños en mi calendario</label>
          <label className="checkbox"><input type="checkbox" checked={pref.ver_aniversarios} onChange={(e) => preferencia('ver_aniversarios', e.target.checked)} />
            <Award size={15} /> Ver aniversarios en la empresa en mi calendario</label>
        </div>
        {error && <div className="alerta error" style={{ marginTop: 10 }}>{error}</div>}
      </div>

      <div className="card">
        <b>Próximos {datos.dias} días</b>
        {datos.proximos.length === 0 && (
          <div className="muted" style={{ padding: '10px 0' }}>
            {pref.ver_cumpleanos || pref.ver_aniversarios ? 'No hay cumpleaños ni aniversarios en los próximos días.' : 'Tienes ocultos los cumpleaños y aniversarios.'}
          </div>
        )}
        {datos.proximos.map((e) => (
          <div key={`${e.tipo}-${e.usuario_id}-${e.fecha}`} className="est-fila">
            <Avatar usuario={{ id: e.usuario_id, nombre: e.nombre, tiene_foto: e.tiene_foto }} tam={36} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <b>{e.nombre}{e.propio ? ' (tú)' : ''}</b>
              <div className="muted" style={{ fontSize: 12 }}>{e.puesto}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="fila" style={{ gap: 6, justifyContent: 'flex-end' }}>
                {e.tipo === 'cumpleanos' ? <Cake size={15} /> : <Award size={15} />}
                {e.tipo === 'cumpleanos' ? 'Cumpleaños' : `${e.anios} año(s) en O-tek`}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>{fmtFecha(e.fecha)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
