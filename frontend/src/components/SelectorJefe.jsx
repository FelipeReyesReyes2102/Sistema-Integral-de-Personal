import { useEffect, useState } from 'react'
import { api } from '../api'

/** Selector del jefe que aprobará (muestra su correo). Excluye al propio empleado. */
export default function SelectorJefe({ empleado, value, onChange }) {
  const [jefes, setJefes] = useState([])

  useEffect(() => {
    api('/jefes').then((js) => {
      const lista = js.filter((j) => j.id !== empleado?.id)
      setJefes(lista)
      if (!value) {
        const porDefecto = lista.find((j) => j.id === empleado?.jefe_id) || (lista.length === 1 ? lista[0] : null)
        if (porDefecto) onChange(porDefecto.id)
      }
    }).catch(() => {})
  }, [empleado?.id])

  return (
    <select value={value || ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">Selecciona…</option>
      {jefes.map((j) => (
        <option key={j.id} value={j.id}>
          {j.nombre}{j.id === empleado?.jefe_id ? ' (jefe directo)' : ''} · {j.email}
        </option>
      ))}
    </select>
  )
}
