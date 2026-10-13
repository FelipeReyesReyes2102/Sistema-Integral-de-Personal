import { useEffect, useState } from 'react'
import { Lock } from 'lucide-react'
import { api } from '../api'
import { CATEGORIAS, ESTADOS, RESULTADOS_CONSULTA, TIPOS_NOMINA, TIPOS_PERMISO, fmtFecha, hhmm, num } from '../utils'
import Modal from './Modal'

function Fila({ k, v }) {
  if (v === undefined || v === null || v === '') return null
  return <div className="ev-fila"><span>{k}</span><div>{v}</div></div>
}

/** Tarjeta con las especificaciones de un evento (se consultan al backend por su id). */
function Evento({ e }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  const cat = CATEGORIAS[e.cat] || { label: e.cat, color: '#888' }

  useEffect(() => {
    if (!e.id) return
    const ruta = e.cat === 'vacaciones' ? `/vacaciones/${e.id}` : e.cat === 'consulta' ? `/consultas/${e.id}` : `/permisos/${e.id}`
    api(ruta).then(setD).catch((err) => setError(err.message))
  }, [e.cat, e.id])

  return (
    <div className="ev-card" style={{ borderLeftColor: cat.color }}>
      <div className="ev-cab">
        <span className="ev-cat" style={{ color: cat.color }}>{cat.label}</span>
        {e.estado && e.estado !== 'registrada' && <span className={`pill ${e.estado}`}>{ESTADOS[e.estado]}</span>}
        {e.cat === 'consulta' && <span className="pill consulta">Servicio médico</span>}
      </div>
      {error && <div className="alerta error">{error}</div>}
      {!e.id && e.cat === 'consulta' && (
        <div className="muted fila" style={{ gap: 6, fontSize: 13 }}>
          <Lock size={14} /> {e.hora_inicio}{e.hora_fin ? ` - ${e.hora_fin}` : ''} · La información clínica solo la ven el paciente, el médico y el administrador.
        </div>
      )}
      {d && e.cat === 'vacaciones' && (
        <>
          <Fila k="Periodo" v={d.periodo_nombre} />
          <Fila k="Fechas" v={`${fmtFecha(d.fecha_inicio)} → ${fmtFecha(d.fecha_fin)}`} />
          <Fila k="Días laborales" v={`${d.dias_habiles} (${num(d.horas)} h)`} />
          <Fila k="Comentario" v={d.comentario} />
          <Fila k="Jefe que aprueba" v={d.aprobador_nombre || 'Administración'} />
          <Fila k="Revisó" v={d.revisado_por_nombre && `${d.revisado_por_nombre} · ${d.fecha_revision?.slice(0, 16).replace('T', ' ')}`} />
          <Fila k="Motivo de rechazo" v={d.motivo_rechazo} />
        </>
      )}
      {d && e.cat !== 'vacaciones' && e.cat !== 'consulta' && (
        <>
          <Fila k="Tipo" v={TIPOS_PERMISO[d.tipo]} />
          {d.tipo === 'home_office'
            ? <Fila k="Fechas" v={`${fmtFecha(d.fecha)} → ${fmtFecha(d.fecha_fin || d.fecha)} (${d.dias ?? '—'} días laborales)`} />
            : <Fila k="Horario" v={`${fmtFecha(d.fecha)} · ${hhmm(d.hora_inicio)} - ${hhmm(d.hora_fin)} (${num(d.horas)} h)`} />}
          <Fila k="Motivo" v={d.motivo} />
          <Fila k="Departamento" v={d.departamento} />
          <Fila k="Tiempo en nómina" v={TIPOS_NOMINA[d.tipo_nomina]} />
          <Fila k="Jefe que aprueba" v={d.aprobador_nombre || 'Administración'} />
          <Fila k="Revisó" v={d.revisado_por_nombre && `${d.revisado_por_nombre} · ${d.fecha_revision?.slice(0, 16).replace('T', ' ')}`} />
          <Fila k="Observaciones" v={d.observaciones} />
          <Fila k="Motivo de rechazo" v={d.motivo_rechazo} />
        </>
      )}
      {d && e.cat === 'consulta' && (
        <>
          <Fila k="Horario" v={`${hhmm(d.hora_inicio)}${d.hora_fin ? ` - ${hhmm(d.hora_fin)}` : ''}`} />
          <Fila k="Atendió" v={d.medico_nombre} />
          <Fila k="Síntomas" v={d.sintomas} />
          <Fila k="Diagnóstico" v={d.diagnostico} />
          <Fila k="Medicamento recetado" v={d.medicamentos?.length ? (
            <ul className="lista-meds">{d.medicamentos.map((m) => (
              <li key={m.id}><b>{m.nombre}</b>{[m.dosis, m.frecuencia, m.duracion].filter(Boolean).map((x) => ` · ${x}`).join('')}</li>
            ))}</ul>) : '—'} />
          <Fila k="Indicaciones" v={d.indicaciones} />
          <Fila k="Resultado" v={RESULTADOS_CONSULTA[d.resultado]} />
        </>
      )}
    </div>
  )
}

/** Ventana con todos los eventos de un día y sus especificaciones. */
export default function EventosDia({ fecha, eventos, festivo, descanso, persona, onClose, pie, cumpleanos = [] }) {
  return (
    <Modal titulo={`${persona ? `${persona} · ` : ''}${fmtFecha(fecha)}`} onClose={onClose}
      pie={<>{pie}<button className="btn" onClick={onClose}>Cerrar</button></>}>
      {(festivo || descanso) && (
        <div className="fila" style={{ gap: 8, marginBottom: 10 }}>
          {festivo && <span className="pill rechazado">Festivo: {festivo}</span>}
          {descanso && <span className="pill borrador">Día de descanso</span>}
        </div>
      )}
      {cumpleanos.length > 0 && (
        <div className="ev-cumples">
          {cumpleanos.map((c) => <div key={c.usuario_id}>🎂 Cumpleaños de <b>{c.nombre}</b>{c.puesto ? <span className="muted"> · {c.puesto}</span> : null}</div>)}
        </div>
      )}
      {eventos.length === 0 && <div className="muted">No hay eventos registrados este día.</div>}
      <div className="ev-lista">
        {eventos.map((e, i) => <Evento key={`${e.cat}-${e.id}-${i}`} e={e} />)}
      </div>
    </Modal>
  )
}
