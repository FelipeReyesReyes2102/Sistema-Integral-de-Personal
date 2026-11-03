import { useEffect, useState } from 'react'
import { Ban, Laptop, Pencil, Plus, Send, Trash2 } from 'lucide-react'
import { api } from '../api'
import FormatoEquipo from '../components/FormatoEquipo'
import SalidaEquipoModal from '../components/SalidaEquipoModal'
import TablaSalidas from '../components/TablaSalidas'

/** Mis salidas de equipo de cómputo (formato F-630-03). */
export default function SalidasEquipo() {
  const [lista, setLista] = useState([])
  const [modal, setModal] = useState(null) // {tipo: 'nueva' | 'editar' | 'formato', salida}
  const [error, setError] = useState('')
  const cargar = () => api('/equipos').then(setLista).catch((e) => setError(e.message))
  useEffect(() => { cargar() }, [])

  async function accion(ruta, metodo, pregunta) {
    if (pregunta && !window.confirm(pregunta)) return
    try {
      await api(ruta, { method: metodo })
      cargar()
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <>
      <div className="card fila" style={{ marginBottom: 16 }}>
        <Laptop size={22} />
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="muted" style={{ fontSize: 13 }}>
            1. Tu jefe la autoriza · 2. TI la revisa · 3. Caseta registra la salida y el regreso.
          </div>
        </div>
        <button className="btn btn-primary" onClick={() => setModal({ tipo: 'nueva' })}><Plus size={16} /> Nueva solicitud</button>
      </div>
      <div className="card">
        {error && <div className="alerta error">{error}</div>}
        <TablaSalidas lista={lista} conEmpleado={false} vacio="Aún no tienes solicitudes de salida de equipo."
          onFormato={(s) => setModal({ tipo: 'formato', salida: s })}
          acciones={(s) => (
            <>
              {s.estado === 'borrador' && (
                <>
                  <button className="icon-btn" title="Editar" onClick={() => setModal({ tipo: 'editar', salida: s })}><Pencil size={16} /></button>{' '}
                  <button className="icon-btn verde" title="Firmar y enviar" onClick={() => setModal({ tipo: 'editar', salida: s })}><Send size={16} /></button>{' '}
                  <button className="icon-btn rojo" title="Eliminar" onClick={() => accion(`/equipos/${s.id}`, 'DELETE', '¿Eliminar este borrador?')}><Trash2 size={16} /></button>
                </>
              )}
              {['solicitado', 'validado'].includes(s.estado) && !s.salida_registrada && (
                <button className="icon-btn rojo" title="Cancelar solicitud"
                  onClick={() => accion(`/equipos/${s.id}/cancelar`, 'POST', '¿Cancelar esta solicitud de salida de equipo?')}><Ban size={16} /></button>
              )}
            </>
          )} />
      </div>
      {(modal?.tipo === 'nueva' || modal?.tipo === 'editar') && (
        <SalidaEquipoModal salida={modal.salida} onClose={() => setModal(null)} onSaved={() => { setModal(null); cargar() }} />
      )}
      {modal?.tipo === 'formato' && <FormatoEquipo salida={modal.salida} onClose={() => setModal(null)} />}
    </>
  )
}
