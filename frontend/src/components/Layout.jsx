import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  CalendarDays, ClipboardCheck, Clock, Home, Stethoscope, KeyRound, ListChecks, LogOut, Menu, PanelLeftClose, PanelLeftOpen,
  PartyPopper, Settings, Users, UsersRound, X,
} from 'lucide-react'
import { api, elegirSede, sedeActiva } from '../api'
import { useAuth } from '../auth'
import { ROLES, esAdmin as esAdminFn } from '../utils'
import Avatar from './Avatar'
import CambiarPassword from './CambiarPassword'
import PerfilUsuario from './PerfilUsuario'

const TITULOS = {
  '/': 'Mis vacaciones y ausencias',
  '/aprobaciones': 'Solicitudes por aprobar',
  '/mi-equipo': 'Mi equipo',
  '/solicitudes': 'Todas las solicitudes',
  '/equipo': 'Calendario general del personal',
  '/empleados': 'Empleados',
  '/turnos': 'Turnos y rotación',
  '/grupos': 'Grupos de planta',
  '/festivos': 'Días festivos',
  '/configuracion': 'Configuración de vacaciones',
  '/consultas': 'Consultas médicas',
}

export const esJefe = (u) => u?.es_jefe || esAdminFn(u)

// Preferencia del menú lateral encogido (solo en este navegador)
const leerColapsado = () => {
  try { return localStorage.getItem('sip-menu-colapsado') === '1' } catch { return false }
}

export default function Layout() {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  const [pendientes, setPendientes] = useState({ total: 0, todas: 0 })
  const [menu, setMenu] = useState(false)
  const [pwd, setPwd] = useState(false)
  const [perfil, setPerfil] = useState(false)
  const [colapsado, setColapsado] = useState(leerColapsado)
  const esAdmin = esAdminFn(user)
  // Sede elegida en el selector; si ya no es una de sus sedes se descarta
  const sedeElegida = (user.sedes || []).some((s) => String(s.id) === sedeActiva()) ? sedeActiva() : ''
  useEffect(() => { if (sedeActiva() && !sedeElegida) elegirSede('') }, [])
  const jefe = esJefe(user)

  useEffect(() => {
    if (!jefe) return
    const cargar = () => api('/pendientes').then(setPendientes).catch(() => {})
    cargar()
    const t = setInterval(cargar, 60000)
    window.addEventListener('pendientes:refrescar', cargar)
    return () => {
      clearInterval(t)
      window.removeEventListener('pendientes:refrescar', cargar)
    }
  }, [jefe])

  useEffect(() => setMenu(false), [pathname])
  useEffect(() => {
    try { localStorage.setItem('sip-menu-colapsado', colapsado ? '1' : '0') } catch { /* sin almacenamiento */ }
  }, [colapsado])

  const titulo = TITULOS[pathname] || (pathname.includes('/vacaciones') ? 'Vacaciones del colaborador' : '')
  const badge = (n) => n > 0 && <span className="badge">{n}</span>
  const link = (to, Icon, texto, extra) => (
    <NavLink to={to} end className="nav-link" title={colapsado ? texto : undefined}>
      <Icon size={18} /> <span className="nav-texto">{texto}</span> {extra}
    </NavLink>
  )

  return (
    <div className={`app ${colapsado ? 'menu-colapsado' : ''}`}>
      {menu && <div className="overlay" style={{ zIndex: 35 }} onClick={() => setMenu(false)} />}
      <aside className={`sidebar ${menu ? 'abierto' : ''}`}>
        <div className="brand">
          <div className="logo-chip">
            <img className="logo-completo" src="/logo-sip.png" alt="SIP · Sistema Integral de Personal" />
            <img className="logo-mini" src="/icono-sip.png" alt="SIP" />
          </div>
          <button className="menu-toggle oculto-movil" onClick={() => setColapsado(!colapsado)}
            title={colapsado ? 'Expandir menú' : 'Encoger menú'} aria-label={colapsado ? 'Expandir menú' : 'Encoger menú'}>
            {colapsado ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
          {(user.sedes || []).length > 1 ? (
            <select className="sede-selector nav-texto" value={sedeElegida} onChange={(e) => elegirSede(e.target.value)}
              title="Sede que estás consultando">
              <option value="">Todas mis sedes ({user.sedes.length})</option>
              {user.sedes.map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
            </select>
          ) : user.sede_nombre && <div className="sede-nombre nav-texto" title="Tu sede">{user.sede_nombre}</div>}
        </div>
        <nav>
          {link('/', Home, 'Mis vacaciones')}
          {user.rol === 'medico' && (
            <>
              <div className="seccion">Servicio médico</div>
              {link('/consultas', Stethoscope, 'Consultas médicas')}
            </>
          )}
          {jefe && (
            <>
              <div className="seccion">Jefe</div>
              {link('/aprobaciones', ListChecks, 'Por aprobar', badge(pendientes.total))}
              {link('/mi-equipo', UsersRound, 'Mi equipo')}
            </>
          )}
          {esAdmin && (
            <>
              <div className="seccion">Administración</div>
              {link('/solicitudes', ClipboardCheck, 'Todas las solicitudes', badge(pendientes.todas))}
              {link('/equipo', CalendarDays, 'Calendario general')}
              {link('/empleados', Users, 'Empleados')}
              {link('/grupos', UsersRound, 'Grupos')}
              {link('/turnos', Clock, 'Turnos')}
              {link('/festivos', PartyPopper, 'Festivos')}
              {link('/configuracion', Settings, 'Configuración')}
            </>
          )}
        </nav>
        <div className="usuario">
          <button type="button" className="usuario-boton" onClick={() => setPerfil(true)}
            title={colapsado ? `${user.nombre} · ${ROLES[user.rol]} — ver mi información` : 'Ver mi información'}>
            <div className="fila" style={{ gap: 10, flexWrap: 'nowrap' }}>
              <Avatar usuario={user} tam={36} />
              <div className="nombre">{user.nombre}</div>
            </div>
            <div className="muted usuario-detalle">
              {ROLES[user.rol]}{user.es_jefe && !esAdmin ? ' · Jefe' : ''}
              {user.jefe_nombre && <div>Reporta a: {user.jefe_nombre}</div>}
            </div>
          </button>
          <div className="fila usuario-acciones" style={{ marginTop: 8 }}>
            {user.puede_usar_password && user.auth_method !== 'microsoft' && (
              <button className="btn btn-sm" onClick={() => setPwd(true)} title="Cambiar contraseña">
                <KeyRound size={14} /> <span className="nav-texto">Contraseña</span>
              </button>
            )}
            <button className="btn btn-sm" onClick={logout} title="Salir"><LogOut size={14} /> <span className="nav-texto">Salir</span></button>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <h1>{titulo}</h1>
          <span className="chip oculto-movil">{ROLES[user.rol]}{user.es_jefe && !esAdmin ? ' · Jefe' : ''}</span>
        </header>
        <main className="contenido">
          <Outlet />
        </main>
      </div>

      <nav className="bottom-nav">
        <NavLink to="/" end><Home size={22} />Inicio</NavLink>
        {jefe && (
          <NavLink to="/aprobaciones">
            <ListChecks size={22} />Por aprobar
            {badge(pendientes.total)}
          </NavLink>
        )}
        {jefe && <NavLink to="/mi-equipo"><UsersRound size={22} />Mi equipo</NavLink>}
        {user.rol === 'medico' && <NavLink to="/consultas"><Stethoscope size={22} />Consultas</NavLink>}
        <button className={menu ? 'active' : ''} onClick={() => setMenu(!menu)}>
          {menu ? <X size={22} /> : <Menu size={22} />}Menú
        </button>
      </nav>
      {pwd && <CambiarPassword onClose={() => setPwd(false)} />}
      {perfil && <PerfilUsuario onClose={() => setPerfil(false)} onPassword={() => setPwd(true)} />}
    </div>
  )
}
