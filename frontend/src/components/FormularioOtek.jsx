import { X } from 'lucide-react'
import FirmaPad from './FirmaPad'

/** Ventana compacta de los formularios O-tek: campos a la izquierda y firma con el botón Enviar a la derecha. */
export default function FormularioOtek({ titulo, subtitulo, onClose, children, onFirma, pieExtra, onEnviar, enviarDeshabilitado,
  enviando, sinFirma = false, textoEnviar = 'Enviar' }) {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`fo ${sinFirma ? 'sin-firma' : ''}`} role="dialog" aria-modal="true" aria-label={titulo}>
        <div className="fo-head">
          <img src="/logo-otek.png" alt="O-tek" />
          <div className="fo-titulos">
            <h2>{titulo}</h2>
            {subtitulo && <span>{subtitulo}</span>}
          </div>
          <button className="icon-btn plain" onClick={onClose} aria-label="Cerrar"><X size={18} /></button>
        </div>
        <div className="fo-cuerpo">
          <div className="fo-body">{children}</div>
          <div className="fo-lado">
            {!sinFirma && (
              <>
                <span className="fo-firma-label">Firma</span>
                <FirmaPad onChange={onFirma} />
              </>
            )}
            <div className="fo-acciones">
              <button className="fo-enviar" onClick={onEnviar} disabled={enviarDeshabilitado || enviando}>
                {enviando ? 'Guardando…' : textoEnviar}
              </button>
              {pieExtra}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Campo con etiqueta compacta (asterisco para obligatorios). */
export function Campo({ label, requerido, children, full, ayuda }) {
  return (
    <label className={`fo-campo ${full ? 'full' : ''}`}>
      <span className="fo-label">{requerido && <i>*</i>}{label}</span>
      {children}
      {ayuda && <span className="fo-ayuda">{ayuda}</span>}
    </label>
  )
}
