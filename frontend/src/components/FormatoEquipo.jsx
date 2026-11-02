import { useEffect, useState } from 'react'
import { Printer } from 'lucide-react'
import { api } from '../api'
import { fmtFecha } from '../utils'
import Modal from './Modal'

const fechaHora = (iso) => (iso ? new Date(iso.slice(0, 19)).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' }) : '')
const X = ({ si }) => <span className="fe-x">{si ? 'X' : ''}</span>

/** Formato F-630-03 "Entrada y salida de equipos de cómputo" con los datos y firmas registrados en SIP-O (para ver o imprimir). */
export default function FormatoEquipo({ salida: s, onClose }) {
  const [firmas, setFirmas] = useState({})
  useEffect(() => { api(`/equipos/${s.id}/firmas`).then(setFirmas).catch(() => {}) }, [s.id])

  return (
    <Modal ancho titulo={`Formato F-630-03 · ${s.usuario_nombre}`} onClose={onClose}
      pie={<>
        <button className="btn" onClick={() => window.print()}><Printer size={15} /> Imprimir</button>
        <button className="btn btn-primary" onClick={onClose}>Cerrar</button>
      </>}>
      <div className="formato-equipo">
        <div className="fe-cab">
          <img src="/logo-otek.png" alt="O-tek" />
          <b>ENTRADA Y SALIDA DE EQUIPOS DE CÓMPUTO</b>
        </div>
        <table>
          <tbody>
            <tr><th>Tipo de equipo</th><td colSpan={5} className="fe-nota">{s.situacion}</td></tr>
            <tr><td>Laptop</td><td><X si={s.tipo_equipo === 'laptop'} /></td><td>Marca</td><td>{s.marca}</td><td>SN / Service Tag</td><td>{s.serie}</td></tr>
            <tr><td>De escritorio</td><td><X si={s.tipo_equipo === 'escritorio'} /></td><td>Modelo</td><td>{s.modelo}</td><td>Accesorios</td><td>{s.accesorios || ''}</td></tr>
            <tr><th>Justificación</th><td colSpan={5}>{s.justificacion}</td></tr>
            <tr><th rowSpan={2}>Plazo</th><td colSpan={2} className="fe-c">Fecha inicio</td><td colSpan={3} className="fe-c">Fecha término</td></tr>
            <tr><td colSpan={2} className="fe-c">{fmtFecha(s.fecha_inicio, false)}</td><td colSpan={3} className="fe-c">{fmtFecha(s.fecha_fin, false)}</td></tr>
            <tr><th>Detalles del equipo</th><td colSpan={5}>{s.detalles || ''}</td></tr>
            <tr><th>Autorización</th><td colSpan={5} className="fe-nota">Firmas registradas en SIP-O</td></tr>
            <tr className="fe-firma">
              <th>Nombre y firma Solicitante</th>
              <td colSpan={5}>{firmas.solicitante && <img src={firmas.solicitante} alt="Firma del solicitante" />}<span>{s.usuario_nombre} · No. {s.usuario_numero}</span></td>
            </tr>
            <tr className="fe-firma">
              <th>Nombre y firma Jefe directo</th>
              <td colSpan={5}>
                {s.revisado_por_nombre && s.estado !== 'solicitado'
                  ? <span><b>{s.estado === 'rechazado' && s.ti_estado !== 'rechazado' ? 'Rechazó' : 'Autorizó'}:</b> {s.revisado_por_nombre} · {fechaHora(s.fecha_revision)}</span>
                  : <span className="fe-nota">Pendiente: {s.aprobador_nombre || 'GH'}</span>}
              </td>
            </tr>
            <tr className="fe-firma">
              <td colSpan={3}>
                {firmas.ti && <img src={firmas.ti} alt="Firma de TI" />}
                <span>{s.ti_estado ? `${s.ti_estado === 'rechazado' ? 'Rechazó' : 'Autorizó'}: ${s.ti_por_nombre} · ${fechaHora(s.ti_fecha)}` : 'Sin revisión de TI'}</span>
                {s.ti_nota && <span className="fe-nota">{s.ti_nota}</span>}
              </td>
              <td colSpan={3}>
                <span>{s.salida_registrada ? `Salida: ${fechaHora(s.salida_registrada)} · ${s.salida_por_nombre}` : 'Sin salida registrada'}</span>
                {s.regreso_registrado && <span>Regreso: {fechaHora(s.regreso_registrado)} · {s.regreso_por_nombre}</span>}
              </td>
            </tr>
            <tr><td colSpan={3} className="fe-c fe-etq">Autorización TI · Sello y Firma TI</td><td colSpan={3} className="fe-c fe-etq">Revisión de Seguridad · Sello Vigilancia</td></tr>
          </tbody>
        </table>
        <div className="fe-pie">
          <span>Este documento contiene información de O-tek México SA de CV considerada de uso interno. Cualquier distribución a terceros o reproducción total y/o parcial será bajo autorización específica.</span>
          <span>Código: F-630-03 · Rev.: C · Elaboró: Analista TI · Aprobó: Gerente GH · Folio SIP-O: EQ-{s.id}</span>
        </div>
      </div>
    </Modal>
  )
}
