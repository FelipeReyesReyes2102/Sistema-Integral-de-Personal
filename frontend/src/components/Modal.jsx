import { X } from 'lucide-react'

export default function Modal({ titulo, onClose, children, pie, ancho = false }) {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${ancho ? 'ancho' : ''}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h3>{titulo}</h3>
          <button className="icon-btn plain" onClick={onClose} aria-label="Cerrar"><X size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {pie && <div className="modal-foot">{pie}</div>}
      </div>
    </div>
  )
}
