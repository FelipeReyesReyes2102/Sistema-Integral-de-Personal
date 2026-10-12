import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarDays, Cloud, Copy, KeyRound, Pencil, Plus, Scale, Search, UserPlus, UserX } from 'lucide-react'
import { api } from '../api'
import Avatar from '../components/Avatar'
import Modal from '../components/Modal'
import { ROLES, esSuperAdmin, fmtFecha, num } from '../utils'
import { useAuth } from '../auth'

const VACIO = {
  numero_empleado: '', nombre: '', email: '', email_personal: '', rol: 'oficina', fecha_ingreso: '', puesto: '', departamento: '',
  turno_id: '', grupo_id: '', jefe_id: '', es_jefe: false, activo: true, password: '', microsoft_oid: '',
}

export default function Empleados() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const soySuper = esSuperAdmin(user)
  const [lista, setLista] = useState([])
  const [turnos, setTurnos] = useState([])
  const [grupos, setGrupos] = useState([])
  const [filtros, setFiltros] = useState({ q: '', rol: '', grupo_id: '' })
  const [editar, setEditar] = useState(null)
  const [saldos, setSaldos] = useState(null)
  const [temporal, setTemporal] = useState(null) // usuario con contraseña temporal recién generada

  async function restablecer(u) {
    if (!window.confirm(`¿Generar una nueva contraseña temporal para ${u.nombre}? La actual dejará de funcionar y se cerrarán sus sesiones.`)) return
    try {
      setTemporal(await api(`/usuarios/${u.id}/password-temporal`, { method: 'POST' }))
      cargar()
    } catch (e) {
      alert(e.message)
    }
  }
  const [estado, setEstado] = useState({})  // qué está configurado de Microsoft (sin credenciales)

  const cargar = () => api('/usuarios', { query: filtros }).then(setLista).catch((e) => alert(e.message))
  useEffect(() => { cargar() }, [filtros])
  useEffect(() => {
    api('/turnos').then(setTurnos)
    api('/grupos').then(setGrupos)
    api('/health').then(setEstado).catch(() => {})
  }, [])

  async function desactivar(u) {
    if (!window.confirm(`¿Desactivar a ${u.nombre}? Ya no podrá iniciar sesión.`)) return
    try {
      await api(`/usuarios/${u.id}`, { method: 'DELETE' })
      cargar()
    } catch (e) {
      alert(e.message)
    }
  }

  const f = (k) => (e) => setFiltros({ ...filtros, [k]: e.target.value })

  return (
    <div className="card">
      <div className="fila" style={{ marginBottom: 14 }}>
        <input style={{ maxWidth: 260 }} placeholder="Buscar nombre, correo o nómina…" value={filtros.q} onChange={f('q')} />
        <select style={{ width: 160 }} value={filtros.rol} onChange={f('rol')}>
          <option value="">Todos los tipos</option>
          {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select style={{ width: 160 }} value={filtros.grupo_id} onChange={f('grupo_id')}>
          <option value="">Todos los grupos</option>
          {grupos.map((g) => <option key={g.id} value={g.id}>{g.nombre}</option>)}
        </select>
        <div className="espacio" />
        <button className="btn btn-primary" onClick={() => setEditar(VACIO)}><Plus size={16} /> Nuevo empleado</button>
      </div>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead>
            <tr><th>No. nómina</th><th>Nombre</th><th>Tipo</th><th>Jefe directo</th><th>Ingreso</th><th>Antigüedad</th><th>Grupo</th><th>Turno</th><th>Estado</th><th /></tr>
          </thead>
          <tbody>
            {lista.map((u) => (
              <tr key={u.id} style={{ opacity: u.activo ? 1 : 0.5 }}>
                <td>{u.numero_empleado}</td>
                <td>
                  <div className="persona">
                    <Avatar usuario={u} tam={34} />
                    <div>
                      <div>{u.nombre} {u.microsoft_vinculado && <span className="chip-ms" title="Cuenta de Microsoft vinculada"><Cloud size={11} /> Microsoft</span>}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {u.email && <span title="Correo corporativo">{u.email}</span>}
                        {u.email && u.email_personal && ' · '}
                        {u.email_personal && <span title="Correo personal">{u.email_personal} (personal)</span>}
                        {!u.email && !u.email_personal && <i>sin correo</i>}
                      </div>
                    </div>
                  </div>
                </td>
                <td>
                  <span className="chip">{ROLES[u.rol]}</span>
                  {u.es_jefe && <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>Jefe · {u.total_a_cargo} a cargo</div>}
                </td>
                <td>{u.jefe_nombre || <span className="muted">Sin jefe</span>}</td>
                <td>{fmtFecha(u.fecha_ingreso, false)}</td>
                <td>{u.antiguedad_anios} año(s)</td>
                <td>{u.grupo_nombre || '—'}</td>
                <td>{u.turno_nombre || '—'}</td>
                <td>
                  {u.activo ? 'Activo' : 'Inactivo'}
                  {u.bloqueado && <div><span className="pill rechazado">Bloqueado</span></div>}
                  {!u.bloqueado && u.debe_cambiar_password && <div><span className="pill solicitado" title="Aún no cambia su contraseña temporal">Contraseña temporal</span></div>}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="icon-btn" title="Vacaciones y permisos" onClick={() => navigate(`/empleados/${u.id}/vacaciones`)}><CalendarDays size={16} /></button>{' '}
                  <button className="icon-btn" title="Saldos y ajustes" onClick={() => setSaldos(u)}><Scale size={16} /></button>{' '}
                  {(soySuper || u.rol !== 'superadmin') && u.activo && (
                    <><button className="icon-btn" title="Restablecer contraseña (temporal de 6 dígitos)" onClick={() => restablecer(u)}><KeyRound size={16} /></button>{' '}</>
                  )}
                  {(soySuper || u.rol !== 'superadmin') && <>
                  <button className="icon-btn" title="Editar" onClick={() => setEditar({ ...u, password: '', email: u.email ?? '', email_personal: u.email_personal ?? '', turno_id: u.turno_id ?? '', grupo_id: u.grupo_id ?? '', jefe_id: u.jefe_id ?? '' })}><Pencil size={16} /></button>{' '}
                  {u.activo && <button className="icon-btn rojo" title="Desactivar" onClick={() => desactivar(u)}><UserX size={16} /></button>}
                  </>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editar && <FormEmpleado inicial={editar} turnos={turnos} grupos={grupos} estado={estado} soySuper={soySuper} onClose={() => setEditar(null)}
        onSaved={(creado) => { setEditar(null); cargar(); if (creado?.password_temporal) setTemporal(creado) }} />}
      {temporal && <PasswordTemporal usuario={temporal} onClose={() => setTemporal(null)} />}
      {saldos && <Saldos usuario={saldos} onClose={() => setSaldos(null)} />}
    </div>
  )
}

function FormEmpleado({ inicial, turnos, grupos, estado, soySuper, onClose, onSaved }) {
  const [form, setForm] = useState(inicial)
  const [error, setError] = useState('')
  const [jefes, setJefes] = useState([])
  const [foto, setFoto] = useState(null)            // nueva foto (data URL) traída de Microsoft
  const [quitarFoto, setQuitarFoto] = useState(false)
  const [ms, setMs] = useState({ buscando: false, error: '', resultado: null })
  const [registrando, setRegistrando] = useState(false)
  const [temporalJefe, setTemporalJefe] = useState(null) // jefe recién registrado: muestra su contraseña temporal
  useEffect(() => { api('/jefes').then((js) => setJefes(js.filter((j) => j.id !== inicial.id))) }, [])
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const graph = estado?.microsoft_graph_configurado
  const msLogin = estado?.microsoft_login_configurado

  async function buscarMicrosoft() {
    if (!form.email) return setMs({ buscando: false, error: 'Escribe el correo corporativo del empleado.', resultado: null })
    setMs({ buscando: true, error: '', resultado: null })
    try {
      const r = await api('/usuarios/microsoft/buscar', { query: { email: form.email } })
      setMs({ buscando: false, error: '', resultado: r })
      setForm((f) => ({
        ...f,
        nombre: r.nombre || f.nombre,
        email: r.email || f.email,
        puesto: r.puesto || f.puesto,
        departamento: r.departamento || f.departamento,
        numero_empleado: f.numero_empleado || r.numero_empleado || '',
        fecha_ingreso: r.fecha_ingreso || f.fecha_ingreso,
        jefe_id: r.jefe_id || f.jefe_id,
        es_jefe: f.es_jefe || r.tiene_reportes,     // tiene personas a cargo en Microsoft
        turno_id: f.turno_id || (f.rol !== 'planta' ? turnoOficina() : '') || '',
        microsoft_oid: r.oid,
      }))
      if (r.foto) { setFoto(r.foto); setQuitarFoto(false) }
    } catch (e) {
      setMs({ buscando: false, error: e.message, resultado: null })
    }
  }

  // Turno por omisión para oficinas: el único turno activo de 8 horas, si solo hay uno
  function turnoOficina() {
    const t = turnos.filter((x) => x.activo !== false && x.horas_jornada === 8)
    return t.length === 1 ? String(t[0].id) : ''
  }

  // Registra en SIP-O al jefe que indica Microsoft (o lo marca como jefe si ya existe) y lo asigna
  async function registrarJefe(nomina) {
    setRegistrando(true)
    try {
      const j = await api('/usuarios/microsoft/registrar-jefe', {
        method: 'POST', body: { email: r.jefe.email, numero_empleado: nomina || null },
      })
      setJefes((js) => (js.some((x) => x.id === j.id) ? js : [...js, j].sort((a, b) => a.nombre.localeCompare(b.nombre))))
      setForm((f) => ({ ...f, jefe_id: j.id }))
      setMs((m) => ({ ...m, error: '', resultado: { ...m.resultado, jefe_id: j.id, jefe_registrado_id: j.id } }))
      if (j.password_temporal) setTemporalJefe(j)
    } catch (e) {
      if (!nomina && e.message.includes('nómina')) {
        const n = window.prompt(`${e.message}\n\nNúmero de nómina de ${r.jefe.nombre}:`)
        if (n && n.trim()) return registrarJefe(n.trim())
      } else {
        setMs((m) => ({ ...m, error: e.message }))
      }
    } finally {
      setRegistrando(false)
    }
  }

  async function guardar() {
    setError('')
    const body = {
      ...form,
      turno_id: form.turno_id ? Number(form.turno_id) : null,
      grupo_id: form.rol === 'planta' && form.grupo_id ? Number(form.grupo_id) : null,
      jefe_id: form.jefe_id ? Number(form.jefe_id) : null,
      email: form.rol === 'planta' ? null : (form.email || '').trim() || null,
      email_personal: (form.email_personal || '').trim() || null,
      password: null,
      microsoft_oid: form.microsoft_oid || null,
      foto: foto || null,
      quitar_foto: quitarFoto,
    }
    try {
      if (inicial.id) {
        await api(`/usuarios/${inicial.id}`, { method: 'PUT', body })
        onSaved()
      } else {
        onSaved(await api('/usuarios', { method: 'POST', body }))
      }
    } catch (e) {
      setError(e.message)
    }
  }

  const r = ms.resultado
  const fotoActual = quitarFoto ? null : foto || (inicial.tiene_foto ? `/api/usuarios/${inicial.id}/foto` : null)

  return (
    <Modal ancho titulo={inicial.id ? 'Editar empleado' : 'Nuevo empleado'} onClose={onClose}
      pie={<><button className="btn" onClick={onClose}>Cancelar</button><button className="btn btn-primary" onClick={guardar}>Guardar</button></>}>
      <div className="form-grid">
        {form.rol === 'planta' ? (
          <div className="full alerta warn" style={{ margin: 0 }}>
            El personal de planta no tiene correo corporativo: registra su <b>correo personal</b> (ahí recibirá sus avisos de turno)
            y podrá entrar con su número de nómina.
          </div>
        ) : (
        <div className="campo full">
          <span>Correo corporativo *</span>
          <div className="ms-buscar">
            <input type="email" value={form.email} onChange={set('email')} placeholder="nombre@o-tek.com"
              onKeyDown={(e) => { if (e.key === 'Enter' && graph) { e.preventDefault(); buscarMicrosoft() } }} />
            {graph && (
              <button className="btn" onClick={buscarMicrosoft} disabled={ms.buscando} type="button">
                <Search size={15} /> {ms.buscando ? 'Buscando…' : 'Buscar en Microsoft'}
              </button>
            )}
          </div>
          {!graph && form.rol !== 'planta' && (
            <span className="muted" style={{ fontSize: 11 }}>
              Para cargar los datos y la foto desde Microsoft, configura MICROSOFT_GRAPH_ENABLED (ver docs/MICROSOFT_ENTRA.md).
            </span>
          )}
        </div>
        )}
        <label className="campo full">Correo personal {form.rol === 'planta' ? '' : '(opcional)'}
          <input type="email" value={form.email_personal || ''} onChange={set('email_personal')} placeholder="nombre@gmail.com" />
          <span className="muted" style={{ fontSize: 11 }}>
            {form.rol === 'planta' ? 'Se usa para los avisos por correo y también sirve para iniciar sesión.' : 'También sirve para iniciar sesión. Los avisos se envían al correo corporativo.'}
          </span>
        </label>
        {ms.error && <div className="full alerta error">{ms.error}</div>}
        {r && (
          <div className="full ms-resultado">
            <Avatar usuario={{ nombre: r.nombre }} src={r.foto} tam={56} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{r.nombre}</div>
              <div className="muted" style={{ fontSize: 12 }}>
                {[r.puesto, r.departamento, r.numero_empleado && `No. ${r.numero_empleado}`].filter(Boolean).join(' · ')}
              </div>
              <div style={{ fontSize: 12, marginTop: 4 }}>
                {r.jefe
                  ? <>Jefe en Microsoft: <b>{r.jefe.nombre}</b>{' '}
                    {r.jefe_id ? '✓ asignado' : r.jefe_registrado_id ? '(registrado, pero no está marcado como jefe)' : '(aún no está registrado en SIP-O)'}</>
                  : 'Sin jefe en Microsoft'}
              </div>
              {r.jefe && !r.jefe_id && r.jefe.email && (
                <button className="btn btn-sm" type="button" style={{ marginTop: 6 }} onClick={() => registrarJefe()} disabled={registrando}>
                  <UserPlus size={14} />{' '}
                  {registrando ? 'Registrando…' : r.jefe_registrado_id ? `Marcar a ${r.jefe.nombre.split(' ')[0]} como jefe y asignarlo` : `Registrar a ${r.jefe.nombre.split(' ')[0]} como jefe desde Microsoft`}
                </button>
              )}
              {r.tiene_reportes && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>Tiene personas a cargo en Microsoft: se marcó "Es jefe".</div>}
              {!r.cuenta_habilitada && <div className="alerta warn" style={{ margin: '6px 0 0' }}>La cuenta está deshabilitada en Microsoft.</div>}
              {r.ya_registrado_id && r.ya_registrado_id !== inicial.id && (
                <div className="alerta warn" style={{ margin: '6px 0 0' }}>Este empleado ya está registrado en el sistema.</div>
              )}
            </div>
            <span className="chip-ms"><Cloud size={11} /> Datos de Microsoft</span>
          </div>
        )}

        <label className="campo">Número de nómina (también sirve para iniciar sesión)
          <input value={form.numero_empleado} onChange={set('numero_empleado')} placeholder="Ej. 2001" />
        </label>
        <label className="campo">Tipo de usuario
          <select value={form.rol} onChange={set('rol')}>
            {Object.entries(ROLES).filter(([k]) => soySuper || k !== 'superadmin').map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {form.rol === 'superadmin' && <span className="muted" style={{ fontSize: 11 }}>Acceso total, incluida la configuración de Microsoft.</span>}
        </label>
        <label className="campo full">Nombre completo<input value={form.nombre} onChange={set('nombre')} /></label>
        <label className="campo">Fecha de ingreso<input type="date" value={form.fecha_ingreso || ''} onChange={set('fecha_ingreso')} /></label>
        <label className="campo">Puesto<input value={form.puesto || ''} onChange={set('puesto')} /></label>
        <label className="campo">Departamento<input value={form.departamento || ''} onChange={set('departamento')} /></label>
        <label className="campo">Turno
          <select value={form.turno_id} onChange={set('turno_id')}>
            <option value="">Sin turno</option>
            {turnos.map((t) => <option key={t.id} value={t.id}>{t.nombre} ({t.hora_entrada.slice(0, 5)}-{t.hora_salida.slice(0, 5)})</option>)}
          </select>
        </label>
        <label className="campo">Grupo (solo planta)
          <select value={form.grupo_id} onChange={set('grupo_id')} disabled={form.rol !== 'planta'}>
            <option value="">Sin grupo</option>
            {grupos.map((g) => <option key={g.id} value={g.id}>{g.nombre}</option>)}
          </select>
        </label>
        <label className="campo">Jefe directo (aprueba sus solicitudes)
          <select value={form.jefe_id} onChange={set('jefe_id')}>
            <option value="">Sin jefe</option>
            {jefes.map((j) => <option key={j.id} value={j.id}>{j.nombre}{j.puesto ? ` — ${j.puesto}` : ''}</option>)}
          </select>
        </label>
        <label className="checkbox" style={{ alignSelf: 'end' }}>
          <input type="checkbox" checked={form.es_jefe} onChange={set('es_jefe')} /> Es jefe (puede aprobar y ver a su equipo)
        </label>
        <div className="campo" style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--muted)' }}>
          <span>Contraseña</span>
          <span style={{ fontSize: 12, lineHeight: 1.5 }}>
            {inicial.id
              ? 'Para dar una nueva contraseña usa "Restablecer contraseña" en la lista de empleados.'
              : 'Al guardar se genera una contraseña temporal de 6 dígitos que el empleado deberá cambiar en su primer inicio de sesión.'}
          </span>
        </div>
        <div className="campo">
          <span>Foto</span>
          <div className="persona">
            <Avatar usuario={{ nombre: form.nombre }} src={fotoActual} tam={44} />
            {fotoActual && <button type="button" className="btn btn-sm" onClick={() => { setFoto(null); setQuitarFoto(true) }}>Quitar foto</button>}
            {!fotoActual && <span className="muted" style={{ fontSize: 12 }}>Se carga desde Microsoft</span>}
          </div>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={form.activo} onChange={set('activo')} /> Activo
        </label>
        {form.microsoft_oid && <div className="muted" style={{ fontSize: 11, alignSelf: 'center' }}>Cuenta de Microsoft vinculada</div>}
        <div className="full muted" style={{ fontSize: 12 }}>
          {form.rol === 'planta'
            ? 'Planta: días de 12 h (año 1 = 8 días). Al menos una vez por periodo debe tomar 4 días seguidos.'
            : 'Oficinas / administrador: días de 8 h (año 1 = 12 días). Al menos una vez por periodo debe tomar 6 días seguidos.'}
        </div>
        {error && <div className="full alerta error">{error}</div>}
      </div>
      {temporalJefe && <PasswordTemporal usuario={temporalJefe} onClose={() => setTemporalJefe(null)} />}
    </Modal>
  )
}

function PasswordTemporal({ usuario, onClose }) {
  const [copiado, setCopiado] = useState(false)
  const acceso = [usuario.numero_empleado && `nómina ${usuario.numero_empleado}`, usuario.email, usuario.email_personal].filter(Boolean).join(' · ')
  return (
    <Modal titulo="Contraseña temporal" onClose={onClose} pie={<button className="btn btn-primary" onClick={onClose}>Listo</button>}>
      <p style={{ marginTop: 0 }}>Entrega esta contraseña a <b>{usuario.nombre}</b>. <b>Solo se muestra esta vez.</b></p>
      <div className="pass-temporal">{usuario.password_temporal}</div>
      <div className="fila" style={{ justifyContent: 'center', marginBottom: 10 }}>
        <button className="btn btn-sm" onClick={() => { navigator.clipboard?.writeText(usuario.password_temporal); setCopiado(true) }}>
          <Copy size={14} /> {copiado ? 'Copiada' : 'Copiar'}
        </button>
      </div>
      <ul className="muted" style={{ fontSize: 13, lineHeight: 1.7, paddingLeft: 18, margin: 0 }}>
        <li>Puede entrar con: {acceso}.</li>
        <li>Al entrar deberá crear su propia contraseña (8 caracteres o más, con letras y números).</li>
        <li>Vence el {usuario.password_temporal_expira ? new Date(`${usuario.password_temporal_expira}Z`).toLocaleString('es-MX') : '—'}; después habrá que restablecerla.</li>
      </ul>
    </Modal>
  )
}

function Saldos({ usuario, onClose }) {
  const [periodos, setPeriodos] = useState([])
  const [edit, setEdit] = useState(null)
  const cargar = () => api('/periodos', { query: { usuario_id: usuario.id } }).then(setPeriodos).catch((e) => alert(e.message))
  useEffect(() => { cargar() }, [])

  async function guardar() {
    try {
      await api(`/periodos/${edit.id}/ajuste`, { method: 'PUT', body: { ajuste_horas: Number(edit.ajuste_horas), nota_ajuste: edit.nota_ajuste } })
      setEdit(null)
      cargar()
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <Modal ancho titulo={`Saldos de ${usuario.nombre}`} onClose={onClose} pie={<button className="btn" onClick={onClose}>Cerrar</button>}>
      <div className="tabla-wrap">
        <table className="tabla">
          <thead><tr><th>Periodo</th><th>Año serv.</th><th>Días ley</th><th>Total</th><th>Usado</th><th>Disponible</th><th>Perdidos</th><th>Vence</th><th>Ajuste (h)</th><th /></tr></thead>
          <tbody>
            {periodos.map((p) => (
              <tr key={p.id}>
                <td>{p.nombre}</td>
                <td>{p.numero}</td>
                <td>{p.dias_ley}</td>
                <td>{num(p.dias_total)} d <span className="muted">({num(p.horas_total)} h)</span></td>
                <td>{num(p.dias_validado + p.dias_solicitado + p.dias_borrador)} d</td>
                <td><b>{num(p.dias_disponible)} d</b></td>
                <td style={{ color: p.dias_perdidos > 0 ? 'var(--danger)' : undefined }}>{p.dias_perdidos > 0 ? `${num(p.dias_perdidos)} d` : '—'}</td>
                <td style={{ color: p.vigente ? '' : 'var(--danger)' }}>{fmtFecha(p.fecha_vencimiento, false)}</td>
                <td>
                  {edit?.id === p.id ? (
                    <div style={{ display: 'grid', gap: 4 }}>
                      <input type="number" step="1" value={edit.ajuste_horas} onChange={(e) => setEdit({ ...edit, ajuste_horas: e.target.value })} />
                      <input placeholder="Nota" value={edit.nota_ajuste || ''} onChange={(e) => setEdit({ ...edit, nota_ajuste: e.target.value })} />
                    </div>
                  ) : <span title={p.nota_ajuste || ''}>{num(p.ajuste_horas)}</span>}
                </td>
                <td>
                  {edit?.id === p.id
                    ? <button className="btn btn-sm btn-primary" onClick={guardar}>Guardar</button>
                    : <button className="icon-btn" onClick={() => setEdit(p)}><Pencil size={14} /></button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        El ajuste en horas permite sumar o restar saldo (p. ej. días pendientes de un sistema anterior). Usa valores negativos para restar.
      </p>
    </Modal>
  )
}
