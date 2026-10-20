import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { api } from '../api'
import { ROLES } from '../utils'
import Avatar from './Avatar'

const sinAcentos = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

/** Resalta en el nombre las palabras buscadas (sin distinguir acentos ni mayúsculas). */
function Resaltado({ texto, palabras }) {
  if (!palabras.length) return texto
  const base = sinAcentos(texto)
  const marcas = new Array(texto.length).fill(false)
  for (const w of palabras) {
    let i = base.indexOf(w)
    while (w && i >= 0) {
      for (let k = i; k < i + w.length; k += 1) marcas[k] = true
      i = base.indexOf(w, i + w.length)
    }
  }
  const partes = []
  let actual = { m: marcas[0], t: '' }
  for (let i = 0; i < texto.length; i += 1) {
    if (marcas[i] !== actual.m) { partes.push(actual); actual = { m: marcas[i], t: '' } }
    actual.t += texto[i]
  }
  partes.push(actual)
  return partes.map((p, i) => (p.m ? <mark key={i}>{p.t}</mark> : <span key={i}>{p.t}</span>))
}

/**
 * Buscador de pacientes: escribe nombre, apellido, número de nómina, puesto, departamento o correo.
 * Flechas para moverse, Enter para elegir, Esc para limpiar.
 */
export default function BuscadorPaciente({ value, onChange }) {
  const [q, setQ] = useState('')
  const [lista, setLista] = useState([])
  const [abierto, setAbierto] = useState(false)
  const [activo, setActivo] = useState(0)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')
  const caja = useRef(null)

  useEffect(() => {
    if (value || !abierto) return undefined
    setCargando(true)
    const t = setTimeout(() => {
      api('/consultas/pacientes', { query: { q, limite: 30 } })
        .then((r) => { setLista(r); setActivo(0); setError('') })
        .catch((e) => setError(e.message))
        .finally(() => setCargando(false))
    }, 180)
    return () => clearTimeout(t)
  }, [q, abierto, value])

  // Cerrar la lista al hacer clic fuera
  useEffect(() => {
    const fuera = (e) => { if (caja.current && !caja.current.contains(e.target)) setAbierto(false) }
    document.addEventListener('mousedown', fuera)
    return () => document.removeEventListener('mousedown', fuera)
  }, [])

  const elegir = (p) => { onChange(p); setQ(''); setAbierto(false) }
  const teclas = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setAbierto(true); setActivo((a) => Math.min(a + 1, lista.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActivo((a) => Math.max(a - 1, 0)) }
    if (e.key === 'Enter' && abierto && lista[activo]) { e.preventDefault(); elegir(lista[activo]) }
    if (e.key === 'Escape') { setQ(''); setAbierto(false) }
  }

  if (value) {
    return (
      <div className="paciente-elegido">
        <Avatar usuario={value} tam={42} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="paciente-nombre">{value.nombre}</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {[`No. ${value.numero_empleado}`, ROLES[value.rol], value.puesto, value.departamento, value.sede_nombre].filter(Boolean).join(' · ')}
          </div>
          {(value.telefono || value.contacto_nombre || value.contacto_telefono) && (
            <div style={{ fontSize: 12, marginTop: 2 }}>
              {value.telefono && <>Tel. {value.telefono}</>}
              {(value.contacto_nombre || value.contacto_telefono) && (
                <>{value.telefono ? ' · ' : ''}Emergencia: {[value.contacto_nombre, value.contacto_telefono].filter(Boolean).join(' · ')}</>
              )}
            </div>
          )}
        </div>
        <button type="button" className="btn btn-sm" onClick={() => { onChange(null); setAbierto(true) }}>Cambiar</button>
      </div>
    )
  }

  const palabras = sinAcentos(q).split(/\s+/).filter(Boolean)
  return (
    <div className="buscador-paciente" ref={caja}>
      <div className="bp-input">
        <Search size={16} />
        <input value={q} placeholder="Nombre, apellido, número de nómina, puesto o departamento…" autoComplete="off"
          onChange={(e) => { setQ(e.target.value); setAbierto(true) }} onFocus={() => setAbierto(true)} onKeyDown={teclas}
          role="combobox" aria-expanded={abierto} aria-controls="bp-lista" aria-label="Buscar paciente" />
        {q && <button type="button" className="icon-btn plain" title="Limpiar" onClick={() => setQ('')}><X size={14} /></button>}
      </div>
      {abierto && (
        <ul className="bp-lista" id="bp-lista" role="listbox">
          {error && <li className="bp-vacio" style={{ color: 'var(--danger)' }}>{error}</li>}
          {!error && cargando && lista.length === 0 && <li className="bp-vacio">Buscando…</li>}
          {!error && !cargando && lista.length === 0 && (
            <li className="bp-vacio">Sin resultados{q ? ` para "${q}"` : ''}. Prueba con un apellido o el número de nómina.</li>
          )}
          {lista.map((p, i) => (
            <li key={p.id} role="option" aria-selected={i === activo} className={i === activo ? 'activo' : ''}
              onMouseEnter={() => setActivo(i)} onMouseDown={(e) => { e.preventDefault(); elegir(p) }}>
              <Avatar usuario={p} tam={30} />
              <div style={{ minWidth: 0 }}>
                <div className="bp-nombre"><Resaltado texto={p.nombre} palabras={palabras} /></div>
                <div className="muted bp-detalle">
                  {[`No. ${p.numero_empleado}`, ROLES[p.rol], p.puesto || p.departamento, p.sede_nombre].filter(Boolean).join(' · ')}
                </div>
              </div>
            </li>
          ))}
          {lista.length >= 30 && <li className="bp-vacio">Mostrando los primeros 30: escribe más para afinar.</li>}
        </ul>
      )}
    </div>
  )
}
