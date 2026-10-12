import { useState } from 'react'
import { api } from '../api'
import Modal from './Modal'

export default function CambiarPassword({ onClose }) {
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [confirma, setConfirma] = useState('')
  const [error, setError] = useState('')
  const [ok, setOk] = useState(false)

  async function guardar() {
    setError('')
    if (nueva !== confirma) return setError('Las contraseñas no coinciden')
    try {
      await api('/auth/cambiar-password', { method: 'POST', body: { actual, nueva } })
      setOk(true)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <Modal titulo="Cambiar contraseña" onClose={onClose}
      pie={ok ? <button className="btn btn-primary" onClick={onClose}>Cerrar</button> : (
        <>
          <button className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={guardar}>Guardar</button>
        </>
      )}>
      {ok ? <div className="alerta ok">Contraseña actualizada.</div> : (
        <div className="form-grid">
          <label className="campo full">Contraseña actual
            <input type="password" value={actual} onChange={(e) => setActual(e.target.value)} />
          </label>
          <div className="full muted" style={{ fontSize: 12 }}>Mínimo 8 caracteres, con letras y números.</div>
          <label className="campo">Nueva contraseña
            <input type="password" value={nueva} onChange={(e) => setNueva(e.target.value)} />
          </label>
          <label className="campo">Confirmar
            <input type="password" value={confirma} onChange={(e) => setConfirma(e.target.value)} />
          </label>
          {error && <div className="alerta error full">{error}</div>}
        </div>
      )}
    </Modal>
  )
}
