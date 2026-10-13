import { MapPin } from 'lucide-react'
import { sedeActiva } from '../api'
import { useAuth } from '../auth'

/** Aviso de la sede a la que se aplican los cambios de la pantalla (solo si el usuario maneja varias sedes). */
export default function SedeActual({ que = 'Los cambios' }) {
  const { user } = useAuth()
  const sedes = user?.sedes || []
  if (sedes.length < 2) return null
  const elegida = sedes.find((s) => String(s.id) === sedeActiva())
  const destino = elegida || sedes.find((s) => s.id === user.sede_id) || sedes[0]
  return (
    <div className="sede-aviso">
      <MapPin size={14} />
      {elegida
        ? <span>{que} se aplican a la sede <b>{elegida.nombre}</b>.</span>
        : <span>Estás viendo <b>todas tus sedes</b>; {que.toLowerCase()} se aplican a <b>{destino?.nombre}</b>. Elige otra sede en el menú.</span>}
    </div>
  )
}
