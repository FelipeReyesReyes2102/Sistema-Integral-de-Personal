import { useEffect, useState } from 'react'
import { Search, ShieldCheck, X } from 'lucide-react'
import { api } from '../api'
import FirmaPad from '../components/FirmaPad'
import FormatoEquipo from '../components/FormatoEquipo'
import Modal from '../components/Modal'
import TablaSalidas from '../components/TablaSalidas'

const FILTROS = {
  revision_ti: 'Por revisar (autorizadas por el jefe)',
  solicitado: 'Esperando al jefe',
  validado: 'Autorizadas',
  fuera: 'Equipos fuera de planta',
  rechazado: 'Rechazadas',
  cancelado: 'Canceladas',
  '': 'Todas',
}

/** TI: salidas de equipo de cómputo de la sede; TI las sella (autoriza) o las rechaza antes de que el equipo salga. */
export default function TI() {
  const [estado, setEstado] = useState('revision_ti')
  const [q, setQ] = useState('')
  const [lista, setLista] = useState([])
  const [error, setError] = useState('')
  const [modal, setModal] = useState(null) // {tipo: 'formato' | 'sellar' | 'rechazar', s, nota, firma, motivo}

  const cargar = () => api('/equipos', { query: { todos: true, estado, q } }).then((l) => { setLista(l); setError('') }).catch((e) => setError(e.message))
  useEffect(() => { const t = setTimeout(cargar, 200); return () => clearTimeout(t) }, [estado, q])

  async function ejecutar(ruta, body) {
    try {
      await api(ruta, { method: 'POST', body })
      setModal(null)
      cargar()
      window.dispatchEvent(new Event('pendientes:refrescar'))
    } catch (e) {
      alert(e.message)
    }
  }

  const revisable = (s) => ['solicitado', 'validado'].includes(s.estado) && !s.salida_registrada
  return (
    <>
      <div className="card">
        <div className="fila" style={{ marginBottom: 14 }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <b style={{ fontSize: 16 }}>Salidas de equipo de cómputo</b>
            <div className="muted" style={{ fontSize: 13 }}>
              El jefe directo autoriza la salida. TI puede sellarla o <b>rechazarla</b> mientras el equipo no haya salido; al rechazarla se avisa al empleado y a su jefe.
            </div>
          </div>
          <select value={estado} onChange={(e) => setEstado(e.target.value)} style={{ width: 260 }}>
            {Object.entries(FILTROS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <div className="bp-input" style={{ width: 260 }}>
            <Search size={16} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Empleado, nómina, marca o serie" />
            {q && <button type="button" className="icon-btn plain" title="Limpiar" onClick={() => setQ('')}><X size={14} /></button>}
          </div>
        </div>
        {error && <div className="alerta error">{error}</div>}
        <TablaSalidas lista={lista} vacio="No hay salidas de equipo con este filtro."
          onFormato={(s) => setModal({ tipo: 'formato', s })}
          acciones={(s) => revisable(s) && (
            <span className="fila" style={{ display: 'inline-flex', gap: 6, flexWrap: 'nowrap' }}>
              {s.estado === 'validado' && s.ti_estado !== 'autorizado' && (
                <button className="btn btn-sm btn-success" onClick={() => setModal({ tipo: 'sellar', s, nota: '', firma: null })}>
                  <ShieldCheck size={14} /> Sellar
                </button>
              )}
              <button className="btn btn-sm btn-danger" onClick={() => setModal({ tipo: 'rechazar', s, motivo: '' })}><X size={14} /> Rechazar</button>
            </span>
          )} />
      </div>

      {modal?.tipo === 'formato' && <FormatoEquipo salida={modal.s} onClose={() => setModal(null)} />}
      {modal?.tipo === 'sellar' && (
        <Modal titulo="Autorización TI (sello y firma)" onClose={() => setModal(null)}
          pie={<>
            <button className="btn" onClick={() => setModal(null)}>Cancelar</button>
            <button className="btn btn-success" onClick={() => ejecutar(`/equipos/${modal.s.id}/ti/autorizar`, { nota: modal.nota.trim() || null, firma: modal.firma })}>
              <ShieldCheck size={14} /> Sellar salida
            </button>
          </>}>
          <p style={{ marginTop: 0 }}><b>{modal.s.usuario_nombre}</b> · {modal.s.marca} {modal.s.modelo} · SN {modal.s.serie}</p>
          <label className="campo">Nota de TI (opcional)
            <input value={modal.nota} onChange={(e) => setModal({ ...modal, nota: e.target.value })} maxLength={1000} placeholder="Ej. equipo inventariado, sin información sensible" />
          </label>
          <div className="campo" style={{ marginTop: 10 }}>
            <span>Firma TI (opcional)</span>
            <FirmaPad onChange={(f) => setModal((m) => ({ ...m, firma: f }))} />
          </div>
        </Modal>
      )}
      {modal?.tipo === 'rechazar' && (
        <Modal titulo="Rechazar salida de equipo" onClose={() => setModal(null)}
          pie={<>
            <button className="btn" onClick={() => setModal(null)}>Cancelar</button>
            <button className="btn btn-danger" disabled={modal.motivo.trim().length < 3}
              onClick={() => ejecutar(`/equipos/${modal.s.id}/ti/rechazar`, { motivo: modal.motivo.trim() })}>Rechazar salida</button>
          </>}>
          <p style={{ marginTop: 0 }}>
            <b>{modal.s.usuario_nombre}</b> · {modal.s.marca} {modal.s.modelo} · SN {modal.s.serie}<br />
            <span className="muted">El equipo no podrá salir de planta. Se avisará por correo al empleado y a su jefe ({modal.s.aprobador_nombre || 'GH'}), y caseta lo verá como rechazado.</span>
          </p>
          <label className="campo">Motivo del rechazo *
            <textarea rows={3} value={modal.motivo} onChange={(e) => setModal({ ...modal, motivo: e.target.value })} maxLength={1000} />
          </label>
        </Modal>
      )}
    </>
  )
}
