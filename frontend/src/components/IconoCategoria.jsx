import { AlarmClock, Award, Cake, DoorOpen, Footprints, Laptop, PartyPopper, Stethoscope, TreePalm } from 'lucide-react'

// Ícono representativo de cada tipo de evento del calendario
const ICONOS = {
  vacaciones: TreePalm,
  home_office: Laptop,
  llegada_tarde: AlarmClock,
  salida_temprana: DoorOpen,
  salida_intermedia: Footprints,
  consulta: Stethoscope,
  consulta_medica: Stethoscope,
  festivo: PartyPopper,
  cumpleanos: Cake,
  aniversario: Award,
}

export default function IconoCategoria({ cat, size = 14, ...props }) {
  const Icono = ICONOS[cat]
  return Icono ? <Icono size={size} aria-hidden="true" {...props} /> : null
}
