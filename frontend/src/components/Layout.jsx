import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BookOpen, Cake, CalendarDays, ClipboardCheck, Clock, DoorOpen, Home, MonitorCheck, Stethoscope, KeyRound, ListChecks, LogOut, Menu, PanelLeftClose, PanelLeftOpen,
  History, PartyPopper, Settings, ShieldCheck, Users, UsersRound, X,
} from 'lucide-react'
import { api, elegirSede, sedeActiva } from '../api'
import { useAuth } from '../auth'
import { ROLES, esAdmin as esAdminFn, esMedico, esTI, sinVacaciones } from '../utils'
import Avatar from './Avatar'
import CambiarPassword from './CambiarPassword'
import PerfilUsuario from './PerfilUsuario'

// Título de cada página y, en una línea, para qué sirve
const PAGINAS = {
  '/': ['Mis vacaciones y ausencias'],
  '/caseta': ['Caseta', 'Revisa quién tiene permiso de salir hoy y solicita el ingreso de quien llega tarde.'],
  '/equipos': ['Salida de equipo de cómputo', 'Pide permiso para sacar un equipo de la empresa y consulta en qué va tu solicitud.'],
  '/cumpleanos': ['Cumpleaños y aniversarios', 'Los del personal de tu sede aparecen en tu calendario; puedes ocultarlos.'],
  '/ti': ['Salidas de equipo (TI)', 'Revisa las salidas de equipo ya autorizadas por el jefe: séllalas o recházalas.'],
  '/aprobaciones': ['Por aprobar', 'Solicitudes de tu personal que esperan tu respuesta.'],
  '/mi-equipo': ['Mi equipo', 'Las personas que te reportan, sus días disponibles y su calendario.'],
  '/solicitudes': ['Todas las solicitudes', 'Todas las solicitudes de tus sedes, con su estado.'],
  '/equipo': ['Calendario general', 'Quién está de vacaciones, con permiso o incapacidad cada día.'],
  '/empleados': ['Empleados', 'Alta, datos y permisos de cada persona.'],
  '/turnos': ['Turnos y rotación', 'Horarios de trabajo y rotación de los grupos de planta.'],
  '/grupos': ['Grupos de planta', 'Grupos de personal de planta y sus integrantes.'],
  '/festivos': ['Días festivos', 'Días que no se trabajan y no se descuentan de las vacaciones.'],
  '/configuracion': ['Configuración', 'Reglas de vacaciones y permisos, correo, Microsoft y SharePoint por sede.'],
  '/consultas': ['Consultas médicas', 'Registra consultas e incapacidades y revisa la bitácora.'],
  '/bitacora': ['Bitácora', 'Quién cambió qué y cuándo.'],
  '/super-admin': ['Super administrador'],
}

export const esJefe = (u) => u?.es_jefe || esAdminFn(u)

// Preferencia del menú lateral encogido (solo en este navegador)
const leerColapsado = () => {
  try { return localStorage.getItem('sip-menu-colapsado') === '1' } catch { return false }
}

/** Manual que corresponde a cada tipo de usuario (en /manuales/, servido por el contenedor web). */
function manualDe(user, jefe) {
  const m = { superadmin: 'superadmin', admin: 'gh', gerencia_gh: 'gh', caseta: 'caseta', medico: 'servicio-medico' }[user.rol]
    || (jefe ? 'jefe' : esTI(user) ? 'ti' : 'empleado')
  return `/manuales/manual-${m}.html`
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

  const conPendientes = jefe || esTI(user) || !sinVacaciones(user)
  useEffect(() => {
    if (!conPendientes) return
    const cargar = () => api('/pendientes').then(setPendientes).catch(() => {})
    cargar()
    const t = setInterval(cargar, 60000)
    window.addEventListener('pendientes:refrescar', cargar)
    return () => {
      clearInterval(t)
      window.removeEventListener('pendientes:refrescar', cargar)
    }
  }, [conPendientes])

  useEffect(() => setMenu(false), [pathname])
  useEffect(() => {
    try { localStorage.setItem('sip-menu-colapsado', colapsado ? '1' : '0') } catch { /* sin almacenamiento */ }
  }, [colapsado])

  const [titulo, descripcion] = PAGINAS[pathname] || [pathname.includes('/vacaciones') ? 'Vacaciones del colaborador' : '']
  // El inicio y el calendario de un colaborador ocupan toda la pantalla: no llevan encabezado
  const conEncabezado = pathname !== '/' && !pathname.includes('/vacaciones')
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
          {!sinVacaciones(user) && (
            <>
              <div className="seccion">Mi espacio</div>
              {link('/', Home, 'Mis vacaciones')}
              {link('/cumpleanos', Cake, 'Cumpleaños')}
            </>
          )}
          {jefe && (
            <>
              <div className="seccion">Mi personal</div>
              {link('/aprobaciones', ListChecks, 'Por aprobar', badge(pendientes.total))}
              {link('/mi-equipo', UsersRound, 'Mi equipo')}
            </>
          )}
          {esTI(user) && (
            <>
              <div className="seccion">TI</div>
              {link('/ti', MonitorCheck, 'Salidas de equipo', badge(pendientes.ti_equipos))}
            </>
          )}
          {user.rol === 'caseta' && (
            <>
              <div className="seccion">Caseta</div>
              {link('/caseta', DoorOpen, 'Permisos y retardos')}
            </>
          )}
          {esMedico(user) && (
            <>
              <div className="seccion">Servicio médico</div>
              {link('/consultas', Stethoscope, 'Consultas médicas')}
            </>
          )}
          {esAdmin && (
            <>
              <div className="seccion">Gestión Humana</div>
              {link('/solicitudes', ClipboardCheck, 'Todas las solicitudes', badge(pendientes.todas))}
              {link('/equipo', CalendarDays, 'Calendario general')}
              {link('/empleados', Users, 'Empleados')}
              {link('/caseta', DoorOpen, 'Caseta')}
              <div className="seccion">Ajustes</div>
              {link('/grupos', UsersRound, 'Grupos')}
              {link('/turnos', Clock, 'Turnos')}
              {link('/festivos', PartyPopper, 'Festivos')}
              {link('/configuracion', Settings, 'Configuración')}
              {link('/bitacora', History, 'Bitácora')}
              {user.rol === 'superadmin' && link('/super-admin', ShieldCheck, 'Super administrador')}
            </>
          )}
          <div className="seccion">Ayuda</div>
          <a href={manualDe(user, jefe)} target="_blank" rel="noopener" className="nav-link" title={colapsado ? 'Manual de usuario' : undefined}>
            <BookOpen size={18} /> <span className="nav-texto">Manual de usuario</span>
          </a>
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
        </header>
        <main className="contenido">
          {conEncabezado && titulo && (
            <div className="pagina-cab">
              <h1>{titulo}</h1>
              {descripcion && <p>{descripcion}</p>}
            </div>
          )}
          <Outlet />
        </main>
      </div>

      <nav className="bottom-nav">
        {!sinVacaciones(user) && <NavLink to="/" end><Home size={22} />Inicio</NavLink>}
        {jefe && (
          <NavLink to="/aprobaciones">
            <ListChecks size={22} />Por aprobar
            {badge(pendientes.total)}
          </NavLink>
        )}
        {jefe && <NavLink to="/mi-equipo"><UsersRound size={22} />Mi equipo</NavLink>}
        {esMedico(user) && <NavLink to="/consultas"><Stethoscope size={22} />Consultas</NavLink>}
        {user.rol === 'caseta' && <NavLink to="/caseta"><DoorOpen size={22} />Caseta</NavLink>}
        {esTI(user) && !esAdmin && <NavLink to="/ti"><MonitorCheck size={22} />TI{badge(pendientes.ti_equipos)}</NavLink>}
        <button className={menu ? 'active' : ''} onClick={() => setMenu(!menu)}>
          {menu ? <X size={22} /> : <Menu size={22} />}Menú
        </button>
      </nav>
      {pwd && <CambiarPassword onClose={() => setPwd(false)} />}
      {perfil && <PerfilUsuario onClose={() => setPerfil(false)} onPassword={() => setPwd(true)} />}
    </div>
  )
}
