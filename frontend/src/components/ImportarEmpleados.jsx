import { useState } from 'react'
import { Eye, EyeOff, FileSpreadsheet, Upload } from 'lucide-react'
import { api } from '../api'
import Modal from './Modal'
import { ROLES, fmtFecha } from '../utils'

const ESTADOS = { nuevo: ['Nuevo', 'validado'], existe: ['Ya existe', 'borrador'], error: ['Con error', 'rechazado'] }

/** Alta masiva desde Excel (Código, Empleado, Fecha de ingreso, periodos, Comentarios): vista previa y confirmación. */
export default function ImportarEmpleados({ onClose, onImportado }) {
  const [archivo, setArchivo] = useState(null)
  const [password, setPassword] = useState('')
  const [ver, setVer] = useState(false)
  const [previa, setPrevia] = useState(null)
  const [hecho, setHecho] = useState(null)
  const [error, setError] = useState('')
  const [trabajando, setTrabajando] = useState(false)
  const [filtro, setFiltro] = useState('')

  async function enviar(aplicar, f = archivo) {
    setError('')
    setTrabajando(true)
    const datos = new FormData()
    datos.append('archivo', f)
    datos.append('aplicar', aplicar ? 'true' : 'false')
    if (aplicar) datos.append('password', password)
    try {
      const r = await api('/usuarios/importar', { method: 'POST', body: datos })
      if (aplicar) {
        setHecho(r)
        onImportado()
      } else setPrevia(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setTrabajando(false)
    }
  }

  const elegir = (e) => {
    const f = e.target.files?.[0]
    setArchivo(f || null)
    setPrevia(null)
    if (f) enviar(false, f)
  }

  const r = hecho || previa
  const filas = (r?.filas || []).filter((x) => !filtro || x.estado === filtro)
  const passwordOk = password.length >= 8

  return (
    <Modal ancho titulo="Importar empleados desde Excel" onClose={onClose}
      pie={hecho ? <button className="btn btn-primary" onClick={onClose}>Listo</button> : (
        <>
          <button className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={!previa || !previa.resumen.nuevo || !passwordOk || trabajando}
            onClick={() => window.confirm(`¿Dar de alta a ${previa.resumen.nuevo} empleado(s) en ${previa.sede}?`) && enviar(true)}>
            <Upload size={15} /> {trabajando ? 'Procesando…' : `Dar de alta ${previa?.resumen.nuevo || ''}`}
          </button>
        </>
      )}>
      {!hecho && (
        <>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
            Columnas: <b>Código</b> (nómina), <b>Empleado</b>, <b>Fecha de ingreso</b>, los dos <b>periodos</b> con días adeudados
            (el más reciente va al periodo actual; «7+8 horas» = 7 días y 8 horas) y <b>Comentarios</b> («Días de 12 horas» = planta;
            si no, oficinas). Los empleados que ya existen no se modifican.
          </p>
          <div className="form-grid">
            <label className="campo"><span><FileSpreadsheet size={14} /> Archivo .xlsx</span>
              <input type="file" accept=".xlsx" onChange={elegir} />
            </label>
            <label className="campo"><span>Contraseña inicial (la cambian al entrar)</span>
              <div className="fila" style={{ gap: 6, flexWrap: 'nowrap' }}>
                <input type={ver ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password" placeholder="Mínimo 8 caracteres" />
                <button type="button" className="icon-btn" title={ver ? 'Ocultar' : 'Mostrar'} onClick={() => setVer(!ver)}>
                  {ver ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
          </div>
        </>
      )}
      {trabajando && !r && <p className="muted">Leyendo el archivo…</p>}
      {error && <div className="alerta error">{error}</div>}
      {r && (
        <>
          <div className={`alerta ${hecho ? 'ok' : 'warn'}`} style={{ margin: '10px 0' }}>
            {hecho ? <b>Se dieron de alta {r.resumen.nuevo} empleado(s) en {r.sede}.</b> : <>Vista previa para <b>{r.sede}</b> · nada se ha guardado todavía.</>}
            {' '}Nuevos: {r.resumen.nuevo} · Ya existen: {r.resumen.existe} · Con error: {r.resumen.error}.
            {hecho && ' Entran con su número de nómina y la contraseña inicial; el sistema les pide cambiarla.'}
          </div>
          <div className="fila" style={{ marginBottom: 8 }}>
            <select style={{ width: 200 }} value={filtro} onChange={(e) => setFiltro(e.target.value)}>
              <option value="">Todos ({r.filas.length})</option>
              {Object.entries(ESTADOS).map(([k, [t]]) => <option key={k} value={k}>{t} ({r.resumen[k]})</option>)}
            </select>
            <span className="muted" style={{ fontSize: 12 }}>Periodos del archivo: {r.periodos.join(' (actual) · ')}{r.periodos.length > 1 ? ' (anterior)' : ''}</span>
          </div>
          <div className="tabla-wrap" style={{ maxHeight: 360, overflowY: 'auto' }}>
            <table className="tabla">
              <thead><tr><th>Nómina</th><th>Nombre</th><th>Tipo</th><th>Ingreso</th><th>Días que se cargan</th><th>Estado</th></tr></thead>
              <tbody>
                {filas.map((x) => (
                  <tr key={x.fila}>
                    <td>{x.nomina}</td>
                    <td>{x.nombre}</td>
                    <td>{ROLES[x.rol]}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{x.fecha_ingreso ? fmtFecha(x.fecha_ingreso, false) : '—'}</td>
                    <td>{(x.periodos || []).join(' · ') || <span className="muted">—</span>}</td>
                    <td>
                      <span className={`pill ${ESTADOS[x.estado][1]}`}>{ESTADOS[x.estado][0]}</span>
                      {x.avisos.map((a) => <div key={a} className="muted" style={{ fontSize: 11 }}>{a}</div>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  )
}
