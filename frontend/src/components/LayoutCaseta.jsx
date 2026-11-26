import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { BookOpen, KeyRound, LogOut } from 'lucide-react'
import { elegirSede, sedeActiva } from '../api'
import { useAuth } from '../auth'
import CambiarPassword from './CambiarPassword'
import AvisosCaseta from './AvisosCaseta'
import { detenerAvisosNativos } from '../nativo'

/** Marco de la app de Caseta (Android): sin menú lateral ni otras secciones de SIP-O, solo Caseta. */
export default function LayoutCaseta() {
  const { user, logout } = useAuth()
  const [pwd, setPwd] = useState(false)
  const sedes = user.sedes || []
  const sedeElegida = sedes.some((s) => String(s.id) === sedeActiva()) ? sedeActiva() : ''
  useEffect(() => { if (sedeActiva() && !sedeElegida) elegirSede('') }, [])

  return (
    <div className="app-caseta">
      <header className="app-caseta-barra">
        <img src="/caseta-192.png" alt="" className="app-caseta-icono" />
        <div className="app-caseta-titulo">
          <strong>Caseta</strong>
          {sedes.length > 1 ? (
            <select value={sedeElegida} onChange={(e) => elegirSede(e.target.value)} title="Sede que estás consultando">
              <option value="">Todas mis sedes ({sedes.length})</option>
              {sedes.map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
            </select>
          ) : <span>{user.sede_nombre || user.nombre}</span>}
        </div>
        <a className="app-caseta-accion" href="/manuales/manual-caseta.html" target="_blank" rel="noopener" title="Manual de caseta">
          <BookOpen size={20} />
        </a>
        {user.puede_usar_password && user.auth_method !== 'microsoft' && (
          <button className="app-caseta-accion" onClick={() => setPwd(true)} title="Cambiar contraseña"><KeyRound size={20} /></button>
        )}
        <button className="app-caseta-accion" onClick={async () => { await detenerAvisosNativos(); logout() }} title="Salir"><LogOut size={20} /></button>
      </header>
      <main className="app-caseta-contenido">
        <AvisosCaseta />
        <Outlet />
      </main>
      <footer className="app-caseta-pie">{user.nombre}</footer>
      {pwd && <CambiarPassword onClose={() => setPwd(false)} />}
    </div>
  )
}

/** Quien entra a la app de Caseta sin el rol correspondiente: solo puede salir. */
export function SinAccesoCaseta() {
  const { user, logout } = useAuth()
  return (
    <div className="app-caseta-aviso">
      <div className="card">
        <img src="/caseta-192.png" alt="" width="64" height="64" />
        <h2>Esta app es solo para Caseta</h2>
        <p>
          La cuenta <b>{user.nombre}</b> no tiene acceso a Caseta. Para tus vacaciones y permisos entra a SIP-O
          desde el navegador en <b>https://sip-o.otek.internal</b>.
        </p>
        <button className="btn btn-primary" onClick={logout}><LogOut size={16} /> Salir</button>
      </div>
    </div>
  )
}
