import { useEffect, useState } from 'react'
import { Briefcase, Cake, Pencil, CalendarDays, Clock, Cloud, IdCard, KeyRound, LogOut, Mail, MapPin, Phone, PhoneCall, ShieldCheck, Stethoscope, UserRound, Users } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { ROLES, diaMes, fmtFecha, num, sinVacaciones } from '../utils'
import Avatar from './Avatar'
import Modal from './Modal'
import MisDatosForm from './MisDatosForm'

function Dato({ icono: Icono, etiqueta, children }) {
  if (children === null || children === undefined || children === '' || children === false) return null
  return (
    <div className="perfil-dato">
      <Icono size={15} />
      <span className="perfil-et">{etiqueta}</span>
      <span className="perfil-val">{children}</span>
    </div>
  )
}

/** Ventana con toda la información del usuario que inició sesión. */
export default function PerfilUsuario({ onClose, onPassword }) {
  const { user, logout } = useAuth()
  const [saldo, setSaldo] = useState(null)
  const [turno, setTurno] = useState(null)
  const [editar, setEditar] = useState(false)

  useEffect(() => {
    if (!sinVacaciones(user)) api('/periodos').then((ps) => {
      const vig = ps.filter((p) => p.vigente)
      setSaldo({ dias: vig.reduce((t, p) => t + p.dias_disponible, 0), periodos: vig })
    }).catch(() => {})
    api('/turnos/mi-turno').then(setTurno).catch(() => {})
  }, [])

  const rol = `${ROLES[user.rol] || user.rol}${user.es_jefe && !['admin', 'gerencia_gh', 'superadmin'].includes(user.rol) ? ' · Jefe' : ''}`
  const otrasSedes = (user.sedes || []).filter((s) => s.id !== user.sede_id).map((s) => s.nombre)
  const antiguedad = user.antiguedad_anios > 0 ? `${user.antiguedad_anios} año(s)` : 'menos de 1 año'

  if (editar) {
    return (
      <Modal titulo="Mis datos personales" onClose={() => setEditar(false)}>
        <MisDatosForm onGuardado={() => setEditar(false)}
          pieExtra={<button type="button" className="btn" onClick={() => setEditar(false)}>Cancelar</button>} />
      </Modal>
    )
  }

  return (
    <Modal titulo="Mi información" onClose={onClose}
      pie={<>
        <button className="btn" onClick={() => setEditar(true)}><Pencil size={15} /> Editar mis datos</button>
        {user.puede_usar_password && user.auth_method !== 'microsoft' && (
          <button className="btn" onClick={() => { onClose(); onPassword() }}><KeyRound size={15} /> Cambiar contraseña</button>
        )}
        <button className="btn" onClick={logout}><LogOut size={15} /> Salir</button>
        <button className="btn btn-primary" onClick={onClose}>Cerrar</button>
      </>}>
      <div className="perfil-cab">
        <Avatar usuario={user} tam={72} />
        <div>
          <div className="perfil-nombre">{user.nombre}</div>
          <div className="muted">{[user.puesto, user.departamento].filter(Boolean).join(' · ')}</div>
          <div className="fila" style={{ gap: 6, marginTop: 6 }}>
            <span className="chip">{rol}</span>
            {user.microsoft_vinculado && <span className="chip-ms"><Cloud size={11} /> Microsoft</span>}
          </div>
        </div>
      </div>

      {saldo && (
        <div className="perfil-saldo">
          <div><b>{num(saldo.dias)}</b> días de vacaciones disponibles</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {saldo.periodos.map((p) => `${p.nombre}: ${num(p.dias_disponible)} d (vence ${fmtFecha(p.fecha_vencimiento, false)})`).join(' · ') || 'Aún sin periodos vigentes'}
          </div>
        </div>
      )}

      <div className="perfil-seccion">Datos laborales</div>
      <Dato icono={IdCard} etiqueta="No. de nómina">{user.numero_empleado}</Dato>
      <Dato icono={MapPin} etiqueta="Sede">{user.sede_nombre}</Dato>
      {otrasSedes.length > 0 && <Dato icono={MapPin} etiqueta="También gestiona">{otrasSedes.join(', ')}</Dato>}
      <Dato icono={CalendarDays} etiqueta="Fecha de ingreso">{user.fecha_ingreso && `${fmtFecha(user.fecha_ingreso, false)} · ${antiguedad}`}</Dato>
      <Dato icono={Briefcase} etiqueta="Tipo de jornada">{user.tipo_jornada_nombre}</Dato>
      <Dato icono={Clock} etiqueta="Turno">
        {turno?.actual ? `${turno.actual.nombre} (${turno.actual.resumen || `${turno.actual.hora_entrada} - ${turno.actual.hora_salida}`})` : user.turno_nombre}
        {turno?.hoy?.especial && ` · hoy ${turno.hoy.especial}: ${turno.hoy.entrada} - ${turno.hoy.salida}`}
        {turno?.rotacion_activa && turno.siguiente_semana?.turno && ` · próxima semana: ${turno.siguiente_semana.turno.nombre}`}
      </Dato>
      <Dato icono={Users} etiqueta="Grupo">{user.grupo_nombre}</Dato>
      <Dato icono={UserRound} etiqueta="Jefe directo">{user.jefe_nombre || 'Sin jefe asignado'}</Dato>
      {user.puede_consultas && <Dato icono={Stethoscope} etiqueta="Servicio médico">Puede registrar consultas e incapacidades</Dato>}
      {(user.es_jefe || user.total_a_cargo > 0) && <Dato icono={Users} etiqueta="Personal a cargo">{`${user.total_a_cargo} persona(s)`}</Dato>}

      <div className="perfil-seccion">Contacto</div>
      <Dato icono={Mail} etiqueta="Correo corporativo">{user.email}</Dato>
      <Dato icono={Mail} etiqueta="Correo personal">{user.email_personal}</Dato>
      <Dato icono={Phone} etiqueta="Teléfono">{user.telefono}</Dato>
      <Dato icono={MapPin} etiqueta="Dirección">{user.direccion}</Dato>
      <Dato icono={PhoneCall} etiqueta="Contacto de emergencia">
        {(user.contacto_nombre || user.contacto_telefono) && [user.contacto_nombre, user.contacto_telefono].filter(Boolean).join(' · ')}
      </Dato>
      <Dato icono={Cake} etiqueta="Cumpleaños">{user.fecha_nacimiento && diaMes(user.fecha_nacimiento)}</Dato>

      <div className="perfil-seccion">Cuenta</div>
      <Dato icono={ShieldCheck} etiqueta="Sesión iniciada con">{user.auth_method === 'microsoft' ? 'Microsoft' : 'Usuario y contraseña'}</Dato>
      <Dato icono={Clock} etiqueta="Último acceso">{user.ultimo_acceso && new Date(`${user.ultimo_acceso.slice(0, 19)}Z`).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })}</Dato>
      <p className="muted" style={{ fontSize: 12, margin: '12px 0 0' }}>
        Tus datos de contacto los puedes actualizar con <b>Editar mis datos</b>; los laborales, pídelos a Gestión Humana (GH) de tu sede.
        {user.proxima_confirmacion && ` Próxima confirmación de datos: ${new Date(`${user.proxima_confirmacion.slice(0, 19)}Z`).toLocaleDateString('es-MX')}.`}
      </p>
    </Modal>
  )
}
