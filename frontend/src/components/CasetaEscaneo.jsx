import { useEffect, useRef, useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, Camera, CheckCircle2, Keyboard, Laptop, QrCode, RefreshCw, Search, Send, UserRound, X, XCircle } from 'lucide-react'
import { api } from '../api'
import { esNativo, escanearNativo } from '../nativo'
import Avatar from './Avatar'

const vibrar = (ok) => { try { navigator.vibrate?.(ok ? 80 : [120, 80, 120]) } catch { /* sin vibración */ } }

/** Lector con la cámara del navegador (Chrome en Android) cuando no está la app nativa. */
function LectorWeb({ formato, onLeido, onCerrar }) {
  const video = useRef(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let stream, activo = true, timer
    async function iniciar() {
      try {
        const formats = formato === 'qr' ? ['qr_code'] : ['code_128', 'code_39', 'code_93', 'ean_13', 'ean_8', 'upc_a', 'upc_e', 'itf', 'codabar', 'data_matrix', 'qr_code']
        const detector = new window.BarcodeDetector({ formats })
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        video.current.srcObject = stream
        await video.current.play()
        const leer = async () => {
          if (!activo) return
          try {
            const r = await detector.detect(video.current)
            if (r.length) { onLeido(r[0].rawValue); return }
          } catch { /* cuadro sin código */ }
          timer = setTimeout(leer, 250)
        }
        leer()
      } catch (e) {
        setError(`No se pudo abrir la cámara: ${e.message}`)
      }
    }
    iniciar()
    return () => { activo = false; clearTimeout(timer); stream?.getTracks().forEach((t) => t.stop()) }
  }, [formato])  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="lector-web" role="dialog" aria-label="Escanear código">
      <video ref={video} playsInline muted />
      <div className="lector-marco" />
      {error && <div className="alerta error">{error}</div>}
      <button className="btn" onClick={onCerrar}><X size={16} /> Cerrar</button>
    </div>
  )
}

const camaraWeb = () => typeof window !== 'undefined' && 'BarcodeDetector' in window && !!navigator.mediaDevices?.getUserMedia

/** Botón para escanear + captura manual del código como respaldo. */
function Escanear({ formato, texto, onCodigo, ocupado }) {
  const [web, setWeb] = useState(false)
  const [manual, setManual] = useState(false)
  const [codigo, setCodigo] = useState('')
  const [error, setError] = useState('')
  const puedeCamara = esNativo() || camaraWeb()

  async function abrir() {
    setError('')
    if (!esNativo()) { setWeb(true); return }
    try {
      const c = await escanearNativo(formato)
      if (c) onCodigo(c)
    } catch (e) {
      setError(e.message)
    }
  }
  return (
    <div className="escanear-bloque">
      {puedeCamara && (
        <button className="btn btn-primary escanear-btn" onClick={abrir} disabled={ocupado}>
          {formato === 'qr' ? <QrCode size={22} /> : <Camera size={22} />} {texto}
        </button>
      )}
      <button className="btn btn-sm" onClick={() => setManual(!manual)} style={{ marginTop: 8 }}>
        <Keyboard size={14} /> {manual ? 'Ocultar captura manual' : 'Escribir el código'}
      </button>
      {manual && (
        <form className="fila" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); if (codigo.trim()) { onCodigo(codigo.trim()); setCodigo('') } }}>
          <input value={codigo} onChange={(e) => setCodigo(e.target.value)} placeholder={formato === 'qr' ? 'Código SIPO-E1…' : 'Código del equipo'} style={{ flex: 1 }} />
          <button className="btn btn-sm btn-primary" disabled={ocupado}>Registrar</button>
        </form>
      )}
      {error && <div className="alerta error" style={{ marginTop: 8 }}>{error}</div>}
      {web && <LectorWeb formato={formato} onCerrar={() => setWeb(false)} onLeido={(c) => { setWeb(false); onCodigo(c) }} />}
    </div>
  )
}

function Resultado({ r, onCambiar, onSolicitar }) {
  const ok = r.con_permiso
  const titulo = r.clase === 'equipo'
    ? `${r.tipo === 'salida' ? 'SALIDA' : 'ENTRADA'} DE EQUIPO ${ok ? 'REGISTRADA' : 'SIN PERMISO'}`
    : ok ? `${r.tipo === 'salida' ? 'SALIDA' : 'ENTRADA'} AUTORIZADA` : `${r.tipo === 'salida' ? 'SALIDA' : 'ENTRADA'} SIN PERMISO`
  return (
    <div className={`escaneo-resultado ${ok ? 'ok' : 'no'}`} role="status">
      <div className="escaneo-titulo">{ok ? <CheckCircle2 size={26} /> : <XCircle size={26} />} {titulo}</div>
      {r.persona && (
        <div className="fila" style={{ gap: 12, flexWrap: 'nowrap', marginTop: 10 }}>
          <Avatar usuario={{ id: r.persona.usuario_id, nombre: r.persona.nombre, tiene_foto: r.persona.tiene_foto }} tam={64} />
          <div style={{ minWidth: 0 }}>
            <div className="caseta-nombre" style={{ fontSize: 17 }}>{r.persona.nombre}</div>
            <div className="muted" style={{ fontSize: 12 }}>No. {r.persona.numero_empleado}{r.persona.departamento ? ` · ${r.persona.departamento}` : ''}</div>
            {r.permiso && <div style={{ fontSize: 13, marginTop: 2 }}><b>{r.permiso.tipo_nombre}</b> · {r.permiso.hora_inicio}–{r.permiso.hora_fin}</div>}
          </div>
        </div>
      )}
      {r.equipo_codigo && <div style={{ marginTop: 8 }}><Laptop size={14} /> Equipo <b>{r.equipo_codigo}</b></div>}
      <p style={{ margin: '10px 0 0' }}>{r.mensaje || r.detalle}</p>
      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Registrado a las {r.hora}{r.repetido ? ' (ya se había registrado hace un momento)' : ''}</div>
      <div className="fila" style={{ marginTop: 10, gap: 8 }}>
        {r.clase === 'persona' && onCambiar && (
          <button className="btn btn-sm" onClick={onCambiar}>
            {r.tipo === 'salida' ? <ArrowDownLeft size={14} /> : <ArrowUpRight size={14} />} Era {r.tipo === 'salida' ? 'una entrada' : 'una salida'}
          </button>
        )}
        {r.clase === 'persona' && !ok && r.tipo === 'entrada' && onSolicitar && (
          <button className="btn btn-sm btn-primary" onClick={onSolicitar}><Send size={14} /> Solicitar ingreso por retardo</button>
        )}
      </div>
    </div>
  )
}

function Personas({ onSolicitar, onCambio }) {
  const [res, setRes] = useState(null)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')
  const ultimo = useRef('')

  async function registrar(codigo, tipo) {
    setOcupado(true)
    setError('')
    try {
      ultimo.current = codigo
      const r = await api('/caseta/escanear', { method: 'POST', body: { codigo, tipo } })
      setRes(r)
      vibrar(r.con_permiso)
      onCambio()
    } catch (e) {
      setRes(null)
      setError(e.message)
      vibrar(false)
    } finally {
      setOcupado(false)
    }
  }
  async function solicitar() {
    try {
      const lista = await api('/caseta/empleados', { query: { q: res.persona.numero_empleado, limite: 5 } })
      const p = lista.find((x) => x.id === res.persona.usuario_id)
      if (p) onSolicitar(p)
    } catch (e) {
      setError(e.message)
    }
  }
  return (
    <div className="card">
      <p className="muted" style={{ marginTop: 0 }}>Escanea el <b>QR del empleado</b> (en su gafete o en SIP-O, en «Mi información»). SIP-O registra si sale o entra y revisa si tiene un permiso aprobado para esta hora.</p>
      <Escanear formato="qr" texto="Escanear QR del empleado" onCodigo={(c) => registrar(c)} ocupado={ocupado} />
      {error && <div className="alerta error" style={{ marginTop: 10 }}><XCircle size={16} /> {error}</div>}
      {res && (
        <Resultado r={res} onSolicitar={solicitar}
          onCambiar={() => registrar(ultimo.current, res.tipo === 'salida' ? 'entrada' : 'salida')} />
      )}
    </div>
  )
}

function BuscarPersona({ valor, onElegir }) {
  const [q, setQ] = useState('')
  const [lista, setLista] = useState([])
  useEffect(() => {
    if (!q.trim()) { setLista([]); return undefined }
    const t = setTimeout(() => api('/caseta/empleados', { query: { q, limite: 8 } }).then(setLista).catch(() => setLista([])), 250)
    return () => clearTimeout(t)
  }, [q])
  if (valor) {
    return (
      <div className="fila" style={{ gap: 8 }}>
        <UserRound size={16} /> <b>{valor.nombre}</b> <span className="muted">No. {valor.numero_empleado}</span>
        <button className="icon-btn plain" title="Quitar" onClick={() => onElegir(null)}><X size={14} /></button>
      </div>
    )
  }
  return (
    <div>
      <div className="bp-input"><Search size={16} /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="¿Quién lleva el equipo? (nombre o nómina)" /></div>
      {lista.length > 0 && (
        <div className="caseta-lista" style={{ marginTop: 6 }}>
          {lista.map((e) => (
            <button key={e.id} className="caseta-item compacto" style={{ textAlign: 'left', cursor: 'pointer' }} onClick={() => { onElegir(e); setQ('') }}>
              <Avatar usuario={{ id: e.id, nombre: e.nombre, tiene_foto: e.tiene_foto }} tam={28} />
              <span><b>{e.nombre}</b> <span className="muted">No. {e.numero_empleado}</span></span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Equipos({ onCambio }) {
  const [codigo, setCodigo] = useState('')
  const [info, setInfo] = useState(null)
  const [tipo, setTipo] = useState('salida')
  const [persona, setPersona] = useState(null)
  const [nota, setNota] = useState('')
  const [res, setRes] = useState(null)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  async function leido(c) {
    setError('')
    setRes(null)
    try {
      const i = await api(`/caseta/equipos/${encodeURIComponent(c)}`)
      setCodigo(i.codigo)
      setInfo(i)
      setTipo(i.sugerido)
      const p = i.ultimo?.persona
      setPersona(i.sugerido === 'entrada' && p ? { id: p.usuario_id, nombre: p.nombre, numero_empleado: p.numero_empleado } : null)
    } catch (e) {
      setError(e.message)
    }
  }
  async function personaPorQr(c) {
    try {
      // El QR del empleado solo identifica a la persona; no registra su salida
      const p = await api('/caseta/persona-qr', { query: { codigo: c } })
      setPersona({ id: p.usuario_id, nombre: p.nombre, numero_empleado: p.numero_empleado })
    } catch (e) {
      setError(e.message)
    }
  }
  async function registrar() {
    setOcupado(true)
    setError('')
    try {
      const r = await api('/caseta/equipos', { method: 'POST', body: { codigo, tipo, usuario_id: persona?.id || null, nota: nota || null } })
      setRes(r)
      vibrar(r.con_permiso)
      setInfo(null)
      setCodigo('')
      setPersona(null)
      setNota('')
      onCambio()
    } catch (e) {
      setError(e.message)
      vibrar(false)
    } finally {
      setOcupado(false)
    }
  }
  return (
    <div className="card">
      <p className="muted" style={{ marginTop: 0 }}>Escanea el <b>código de barras</b> del equipo de cómputo. Para una salida, indica quién lo lleva: SIP-O revisa si tiene un permiso «Salida de equipo» aprobado para hoy.</p>
      {!info && <Escanear formato="barras" texto="Escanear código del equipo" onCodigo={leido} ocupado={ocupado} />}
      {info && (
        <div className="equipo-form">
          <div className="fila" style={{ gap: 8 }}>
            <Laptop size={18} /> <b style={{ fontSize: 16 }}>{codigo}</b>
            <button className="icon-btn plain" title="Escanear otro" onClick={() => { setInfo(null); setCodigo('') }}><X size={14} /></button>
          </div>
          {info.ultimo && (
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              Último movimiento: {info.ultimo.tipo} el {info.ultimo.fecha} a las {info.ultimo.hora}{info.ultimo.persona ? ` · ${info.ultimo.persona.nombre}` : ''}
            </div>
          )}
          <div className="segmentado" style={{ margin: '12px 0' }}>
            <button className={tipo === 'salida' ? 'activo' : ''} onClick={() => setTipo('salida')}><ArrowUpRight size={14} /> Sale</button>
            <button className={tipo === 'entrada' ? 'activo' : ''} onClick={() => setTipo('entrada')}><ArrowDownLeft size={14} /> Entra</button>
          </div>
          <BuscarPersona valor={persona} onElegir={setPersona} />
          {!persona && esNativo() && (
            <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={async () => { try { const c = await escanearNativo('qr'); if (c) personaPorQr(c) } catch (e) { setError(e.message) } }}>
              <QrCode size={14} /> Escanear QR de la persona
            </button>
          )}
          <input value={nota} onChange={(e) => setNota(e.target.value)} placeholder="Nota (opcional): marca, modelo, accesorios…" style={{ width: '100%', marginTop: 10 }} maxLength={300} />
          <button className="btn btn-primary escanear-btn" style={{ marginTop: 12 }} onClick={registrar} disabled={ocupado}>
            Registrar {tipo === 'salida' ? 'salida' : 'entrada'}
          </button>
        </div>
      )}
      {error && <div className="alerta error" style={{ marginTop: 10 }}><XCircle size={16} /> {error}</div>}
      {res && <Resultado r={res} />}
    </div>
  )
}

function MovimientosHoy({ version }) {
  const [lista, setLista] = useState([])
  const cargar = () => api('/caseta/movimientos').then(setLista).catch(() => {})
  useEffect(() => { cargar() }, [version])
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="fila" style={{ marginBottom: 8 }}>
        <b>Registros de hoy</b><div className="espacio" />
        <button className="btn btn-sm" onClick={cargar}><RefreshCw size={14} /> Actualizar</button>
      </div>
      {lista.length === 0 && <div className="muted" style={{ padding: 12, textAlign: 'center' }}>Todavía no hay entradas ni salidas registradas hoy.</div>}
      <div className="caseta-lista">
        {lista.map((m) => (
          <div key={m.id} className="caseta-item compacto" style={{ borderLeftColor: m.con_permiso ? '#2e7d32' : '#c62828' }}>
            {m.clase === 'equipo' ? <Laptop size={22} /> : <Avatar usuario={{ id: m.persona?.usuario_id, nombre: m.persona?.nombre || '?', tiene_foto: m.persona?.tiene_foto }} tam={32} />}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div><b>{m.hora}</b> · {m.tipo === 'salida' ? 'Salida' : 'Entrada'}{m.clase === 'equipo' ? ` de equipo ${m.equipo_codigo}` : ''}{m.persona ? ` · ${m.persona.nombre}` : ''}</div>
              <div className="muted" style={{ fontSize: 12 }}>{m.detalle}</div>
            </div>
            {m.con_permiso ? <CheckCircle2 size={18} color="#2e7d32" /> : <XCircle size={18} color="#c62828" />}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Pestaña Escanear de Caseta: personas por QR y equipos de cómputo por código de barras. */
export default function CasetaEscaneo({ onSolicitar }) {
  const [modo, setModo] = useState('personas')
  const [version, setVersion] = useState(0)
  const cambio = () => setVersion((v) => v + 1)
  return (
    <>
      <div className="segmentado" role="tablist" style={{ marginBottom: 10 }}>
        <button role="tab" aria-selected={modo === 'personas'} className={modo === 'personas' ? 'activo' : ''} onClick={() => setModo('personas')}><QrCode size={14} /> Personas</button>
        <button role="tab" aria-selected={modo === 'equipos'} className={modo === 'equipos' ? 'activo' : ''} onClick={() => setModo('equipos')}><Laptop size={14} /> Equipos</button>
      </div>
      {modo === 'personas' ? <Personas onSolicitar={onSolicitar} onCambio={cambio} /> : <Equipos onCambio={cambio} />}
      <MovimientosHoy version={version} />
    </>
  )
}
