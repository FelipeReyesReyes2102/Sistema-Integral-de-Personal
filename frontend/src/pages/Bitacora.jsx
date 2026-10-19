import { useEffect, useState } from 'react'
import { ArrowRight, CalendarCheck, Download, Search, Settings } from 'lucide-react'
import { api } from '../api'

const SECCIONES = {
  configuracion: { titulo: 'Cambios en configuración', icono: Settings,
    ayuda: 'Sedes, política, jornadas, turnos, grupos, festivos, tabla de antigüedad, rotación, correo y Microsoft.' },
  vacaciones: { titulo: 'Registros de vacaciones y permisos', icono: CalendarCheck,
    ayuda: 'Vacaciones, permisos y home office creados, editados, enviados, validados, rechazados, cancelados o eliminados, y ajustes de saldo.' },
}
const ACCIONES = {
  crear: { t: 'Alta', c: 'bt-crear' }, editar: { t: 'Cambio', c: 'bt-editar' },
  estado: { t: 'Cambio de estado', c: 'bt-estado' }, eliminar: { t: 'Eliminación', c: 'bt-eliminar' },
}
const FILTROS = { desde: '', hasta: '', accion: '', entidad: '', q: '' }

const fechaLocal = (iso) => new Date(`${String(iso).slice(0, 19)}Z`)
  .toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })

function Cambios({ lista, accion }) {
  if (!lista.length) return <span className="muted">—</span>
  return (
    <ul className="bt-cambios">
      {lista.map((c) => (
        <li key={c.campo}>
          <b>{c.campo}:</b>{' '}
          {accion === 'crear' || c.antes == null ? <span className="bt-nuevo">{c.despues ?? '—'}</span>
            : c.despues == null ? <span className="bt-viejo">{c.antes}</span>
              : <><span className="bt-viejo">{c.antes}</span> <ArrowRight size={11} /> <span className="bt-nuevo">{c.despues}</span></>}
          {accion !== 'crear' && accion !== 'eliminar' && c.antes != null && c.despues == null && <span className="muted"> (quitado)</span>}
          {accion !== 'crear' && c.antes == null && <span className="muted"> (agregado)</span>}
        </li>
      ))}
    </ul>
  )
}

/** Bitácora: quién cambió qué y cuándo, en la configuración y en los registros de vacaciones. */
export default function Bitacora() {
  const [seccion, setSeccion] = useState('configuracion')
  const [filtros, setFiltros] = useState(FILTROS)
  const [datos, setDatos] = useState({ items: [], hay_mas: false, entidades: [] })
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')

  const consultar = async (mas = false) => {
    setCargando(true)
    setError('')
    try {
      const query = { seccion, limite: 50, ...Object.fromEntries(Object.entries(filtros).filter(([, v]) => v)) }
      if (mas && datos.items.length) query.antes_de = datos.items[datos.items.length - 1].id
      const r = await api('/bitacora', { query })
      setDatos(mas ? { ...r, items: [...datos.items, ...r.items] } : r)
    } catch (e) {
      setError(e.message)
    } finally {
      setCargando(false)
    }
  }
  // Las fechas y listas se aplican al momento; la búsqueda, al dejar de escribir
  useEffect(() => {
    const t = setTimeout(() => consultar(), filtros.q ? 350 : 0)
    return () => clearTimeout(t)
  }, [seccion, filtros])

  const set = (k) => (e) => setFiltros({ ...filtros, [k]: e.target.value })
  const cambiarSeccion = (s) => { setSeccion(s); setFiltros(FILTROS); setDatos({ items: [], hay_mas: false, entidades: [] }) }

  function exportar() {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const filas = [['Fecha', 'Usuario', 'Acción', 'Elemento', 'Descripción', 'Sede', 'Cambios', 'IP']]
    datos.items.forEach((b) => filas.push([fechaLocal(b.fecha), b.actor_nombre, ACCIONES[b.accion]?.t || b.accion, b.entidad,
      b.descripcion, b.sede_nombre, b.cambios.map((c) => `${c.campo}: ${c.antes ?? '—'} → ${c.despues ?? '—'}`).join(' | '), b.ip]))
    const blob = new Blob([`﻿${filas.map((f) => f.map(esc).join(',')).join('\r\n')}`], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `bitacora-${seccion}-${new Date().toLocaleDateString('en-CA')}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const S = SECCIONES[seccion]
  return (
    <>
      <div className="card">
        <div className="bt-tabs" role="tablist">
          {Object.entries(SECCIONES).map(([k, s]) => (
            <button key={k} role="tab" aria-selected={seccion === k} className={`bt-tab ${seccion === k ? 'on' : ''}`} onClick={() => cambiarSeccion(k)}>
              <s.icono size={16} /> {s.titulo}
            </button>
          ))}
        </div>
        <p className="muted" style={{ margin: '10px 0 12px', fontSize: 13 }}>{S.ayuda} Se registra automáticamente quién hizo cada cambio, cuándo y qué valores cambiaron.</p>

        <div className="bt-filtros">
          <label className="campo">Desde<input type="date" value={filtros.desde} max={filtros.hasta || undefined} onChange={set('desde')} /></label>
          <label className="campo">Hasta<input type="date" value={filtros.hasta} min={filtros.desde || undefined} onChange={set('hasta')} /></label>
          <label className="campo">Elemento
            <select value={filtros.entidad} onChange={set('entidad')}>
              <option value="">Todos</option>
              {datos.entidades.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
          </label>
          <label className="campo">Acción
            <select value={filtros.accion} onChange={set('accion')}>
              <option value="">Todas</option>
              {Object.entries(ACCIONES).filter(([k]) => seccion === 'vacaciones' || k !== 'estado').map(([k, a]) => <option key={k} value={k}>{a.t}</option>)}
            </select>
          </label>
          <label className="campo bt-buscar">Buscar
            <span className="bt-input-icono"><Search size={14} /><input value={filtros.q} onChange={set('q')} placeholder="Usuario, empleado, nombre, valor…" /></span>
          </label>
          <div className="bt-acciones">
            {Object.values(filtros).some(Boolean) && <button className="btn btn-sm" onClick={() => setFiltros(FILTROS)}>Limpiar</button>}
            <button className="btn btn-sm" onClick={exportar} disabled={!datos.items.length} title="Exporta lo que se muestra"><Download size={14} /> CSV</button>
          </div>
        </div>

        {error && <div className="alerta error">{error}</div>}
        <div className="tabla-wrap">
          <table className="tabla bt-tabla">
            <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Elemento</th><th>Detalle del cambio</th></tr></thead>
            <tbody>
              {datos.items.map((b) => (
                <tr key={b.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{fechaLocal(b.fecha)}</td>
                  <td>{b.actor_nombre || 'Sistema'}{b.ip && <div className="muted" style={{ fontSize: 11 }}>{b.ip}</div>}</td>
                  <td><span className={`bt-accion ${ACCIONES[b.accion]?.c || ''}`}>{ACCIONES[b.accion]?.t || b.accion}</span></td>
                  <td>
                    <div className="muted" style={{ fontSize: 11 }}>{b.entidad}</div>
                    <b>{b.descripcion}</b>
                    {b.sede_nombre && <div className="muted" style={{ fontSize: 11 }}>{b.sede_nombre}</div>}
                  </td>
                  <td><Cambios lista={b.cambios} accion={b.accion} /></td>
                </tr>
              ))}
              {!datos.items.length && !cargando && (
                <tr><td colSpan={5} className="muted" style={{ textAlign: 'center', padding: 24 }}>
                  {Object.values(filtros).some(Boolean) ? 'No hay cambios con esos filtros.' : 'Aún no hay cambios registrados en este apartado.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="fila" style={{ marginTop: 10 }}>
          <span className="muted" style={{ fontSize: 12 }}>{datos.items.length} registro(s){cargando ? ' · cargando…' : ''}</span>
          <div className="espacio" />
          {datos.hay_mas && <button className="btn btn-sm" disabled={cargando} onClick={() => consultar(true)}>Cargar más</button>}
        </div>
      </div>
    </>
  )
}
