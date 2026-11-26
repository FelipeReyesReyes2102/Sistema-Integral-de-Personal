import { useEffect, useRef, useState } from 'react'
import { Bell, BellRing, X } from 'lucide-react'
import { api } from '../api'
import { esNativo, iniciarAvisosNativos } from '../nativo'

const CLAVE = 'sip-caseta-avisos-vistos'
const leerVistos = () => {
  try { return new Set(JSON.parse(localStorage.getItem(CLAVE) || '[]')) } catch { return null }
}
const guardarVistos = (ids) => {
  try { localStorage.setItem(CLAVE, JSON.stringify([...ids].slice(-500))) } catch { /* sin almacenamiento */ }
}
const hoyTexto = (a) => (a.es_hoy ? 'HOY' : a.fecha.split('-').reverse().slice(0, 2).join('/'))
export const textoAviso = (a) => `${hoyTexto(a)} ${a.hora} · ${a.nombre} — ${a.tipo_nombre}`

/**
 * Avisos de permisos por horas recién aprobados (primero los de hoy).
 * En la app de Android el servicio nativo manda la notificación aunque la app esté en segundo plano;
 * aquí además se muestran dentro de la app y, en el navegador, como notificación del sistema si se permitió.
 */
export default function AvisosCaseta() {
  const [nuevos, setNuevos] = useState([])
  const [permiso, setPermiso] = useState(() => (typeof Notification !== 'undefined' ? Notification.permission : 'unsupported'))
  const vistos = useRef(leerVistos())

  useEffect(() => {
    iniciarAvisosNativos()
    let vivo = true
    const revisar = () => api('/caseta/avisos').then(({ avisos }) => {
      if (!vivo) return
      const primera = vistos.current === null
      const conocidos = vistos.current || new Set()
      const recien = avisos.filter((a) => !conocidos.has(a.id))
      avisos.forEach((a) => conocidos.add(a.id))
      vistos.current = conocidos
      guardarVistos(conocidos)
      if (primera || !recien.length) return  // la primera vez solo se toma nota de los que ya existían
      setNuevos((n) => [...recien, ...n].slice(0, 20))
      try { navigator.vibrate?.([100, 60, 100]) } catch { /* sin vibración */ }
      if (!esNativo() && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        const hoy = recien.filter((a) => a.es_hoy)
        const lista = hoy.length ? hoy : recien
        new Notification(hoy.length ? 'Nuevo permiso para HOY' : 'Nuevo permiso aprobado', {
          body: lista.map(textoAviso).join('\n'), icon: '/caseta-192.png', tag: 'sip-caseta', renotify: true,
        })
      }
    }).catch(() => {})
    revisar()
    const t = setInterval(revisar, 60000)
    return () => { vivo = false; clearInterval(t) }
  }, [])

  const activar = () => Notification.requestPermission().then(setPermiso).catch(() => {})
  const ordenados = [...nuevos].sort((a, b) => (b.es_hoy - a.es_hoy) || a.fecha.localeCompare(b.fecha) || a.hora.localeCompare(b.hora))

  return (
    <>
      {!esNativo() && permiso === 'default' && (
        <button className="avisos-activar" onClick={activar}><Bell size={14} /> Activar avisos de permisos nuevos</button>
      )}
      {ordenados.length > 0 && (
        <div className="avisos-caseta" role="status">
          <div className="fila" style={{ gap: 6 }}>
            <BellRing size={16} /> <b>{ordenados.length === 1 ? 'Nuevo permiso aprobado' : `${ordenados.length} permisos nuevos`}</b>
            <div className="espacio" />
            <button className="icon-btn plain" title="Cerrar" onClick={() => setNuevos([])}><X size={14} /></button>
          </div>
          {ordenados.map((a) => (
            <div key={a.id} className={`aviso-fila ${a.es_hoy ? 'hoy' : ''}`}>
              <span className="aviso-cuando">{hoyTexto(a)} {a.hora}</span> {a.nombre} · <b>{a.tipo_nombre}</b>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
