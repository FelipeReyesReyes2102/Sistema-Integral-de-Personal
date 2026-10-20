import { LogOut, UserCheck } from 'lucide-react'
import { useAuth } from '../auth'
import MisDatosForm from '../components/MisDatosForm'

/** Cada 6 meses (desde el registro o el último cambio) el usuario confirma o actualiza sus datos personales. */
export default function ConfirmarDatos() {
  const { user, logout } = useAuth()
  return (
    <div className="login-page">
      <img src="/logo-sip.png" alt="SIP · Sistema Integral de Personal" className="login-logo" />
      <svg className="login-ola" viewBox="0 0 1440 600" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0,0 C360,140 720,190 1000,160 C1200,140 1330,90 1440,105 L1440,600 L0,600 Z" />
      </svg>
      <div className="login-card confirmar-datos">
        <div className="login-avatar"><UserCheck size={30} /></div>
        <h1>Confirma tus datos</h1>
        <p className="login-sub">
          Hola {user.nombre.split(' ')[0]}, cada 6 meses te pedimos revisar tus datos personales. Corrige lo que haya cambiado
          y confirma para continuar.
        </p>
        <MisDatosForm textoGuardar="Guardar y continuar"
          pieExtra={<button type="button" className="btn" onClick={logout}><LogOut size={15} /> Salir</button>} />
      </div>
    </div>
  )
}
