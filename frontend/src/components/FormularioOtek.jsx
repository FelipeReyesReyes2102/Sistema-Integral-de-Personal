import { X } from 'lucide-react'
import FirmaPad from './FirmaPad'

/** Contenedor con el estilo de los formularios O-tek: encabezado, campos y pie con firma y botón Enviar. */
export default function FormularioOtek({ titulo, onClose, children, onFirma, pieExtra, onEnviar, enviarDeshabilitado, enviando,
  sinFirma = false, textoEnviar = 'Enviar' }) {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="fo" role="dialog" aria-modal="true" aria-label={titulo}>
        <button className="fo-cerrar" onClick={onClose} aria-label="Cerrar"><X size={20} /></button>
        <div className="fo-card fo-head">
          <h2>{titulo}</h2>
          <img src="/logo-otek.png" alt="O-tek" />
        </div>
        <div className="fo-card fo-body">{children}</div>
        <div className="fo-card fo-pie">
          {!sinFirma && (
            <>
              <span className="fo-firma-label">Firma:</span>
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
  )
}

/** Campo con etiqueta al estilo del formulario (asterisco para obligatorios). */
export function Campo({ label, requerido, children, full, ayuda }) {
  return (
    <label className={`fo-campo ${full ? 'full' : ''}`}>
      <span className="fo-label">{requerido && <i>*</i>}{label}</span>
      {children}
      {ayuda && <span className="fo-ayuda">{ayuda}</span>}
    </label>
  )
}
