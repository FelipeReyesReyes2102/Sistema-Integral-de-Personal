import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { useAuth } from './auth'
import { esAdmin, esMedico, esSuperAdmin } from './utils'
import Layout, { esJefe } from './components/Layout'
import Login from './pages/Login'
import CambioObligatorio from './pages/CambioObligatorio'
import ConfirmarDatos from './pages/ConfirmarDatos'
import MisVacaciones from './pages/MisVacaciones'
import Solicitudes from './pages/Solicitudes'
import MiEquipo from './pages/MiEquipo'
import Empleados from './pages/Empleados'
import Turnos from './pages/Turnos'
import Grupos from './pages/Grupos'
import Festivos from './pages/Festivos'
import Configuracion from './pages/Configuracion'
import Bitacora from './pages/Bitacora'
import SuperAdmin from './pages/SuperAdmin'
import CalendarioEquipo from './pages/CalendarioEquipo'
import Consultas from './pages/Consultas'

function SoloAdmin({ children }) {
  const { user } = useAuth()
  return esAdmin(user) ? children : <Navigate to="/" replace />
}

function SoloSuperAdmin({ children }) {
  const { user } = useAuth()
  return esSuperAdmin(user) ? children : <Navigate to="/" replace />
}

function SoloMedico({ children }) {
  const { user } = useAuth()
  return esMedico(user) ? children : <Navigate to="/" replace />
}

function SoloJefe({ children }) {
  const { user } = useAuth()
  return esJefe(user) ? children : <Navigate to="/" replace />
}

function VacacionesEmpleado() {
  const { id } = useParams()
  return <MisVacaciones key={id} usuarioId={Number(id)} />
}

export default function App() {
  const { user, cargando } = useAuth()
  if (cargando) return <div style={{ padding: 40 }}>Cargando…</div>
  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }
  // Primer inicio de sesión con contraseña temporal: solo puede cambiarla
  if (user.debe_cambiar_password && user.auth_method !== 'microsoft') return <CambioObligatorio />
  // Cada 6 meses desde el registro o el último cambio: confirmar o actualizar datos personales
  if (user.debe_confirmar_datos) return <ConfirmarDatos />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<MisVacaciones />} />
        <Route path="/consultas" element={<SoloMedico><Consultas /></SoloMedico>} />
        <Route path="/aprobaciones" element={<SoloJefe><Solicitudes modo="jefe" /></SoloJefe>} />
        <Route path="/mi-equipo" element={<SoloJefe><MiEquipo /></SoloJefe>} />
        <Route path="/mi-equipo/:id/vacaciones" element={<SoloJefe><VacacionesEmpleado /></SoloJefe>} />
        <Route path="/solicitudes" element={<SoloAdmin><Solicitudes modo="admin" /></SoloAdmin>} />
        <Route path="/equipo" element={<SoloAdmin><CalendarioEquipo /></SoloAdmin>} />
        <Route path="/empleados" element={<SoloAdmin><Empleados /></SoloAdmin>} />
        <Route path="/empleados/:id/vacaciones" element={<SoloAdmin><VacacionesEmpleado /></SoloAdmin>} />
        <Route path="/turnos" element={<SoloAdmin><Turnos /></SoloAdmin>} />
        <Route path="/grupos" element={<SoloAdmin><Grupos /></SoloAdmin>} />
        <Route path="/festivos" element={<SoloAdmin><Festivos /></SoloAdmin>} />
        <Route path="/configuracion" element={<SoloAdmin><Configuracion /></SoloAdmin>} />
        <Route path="/bitacora" element={<SoloAdmin><Bitacora /></SoloAdmin>} />
        <Route path="/super-admin" element={<SoloSuperAdmin><SuperAdmin /></SoloSuperAdmin>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
