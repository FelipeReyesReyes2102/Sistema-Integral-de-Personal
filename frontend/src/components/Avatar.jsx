/** Foto del usuario (de Microsoft) o sus iniciales. */
export default function Avatar({ usuario, tam = 32, src }) {
  const iniciales = (usuario?.nombre || '?').split(' ').filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
  const estilo = { width: tam, height: tam, fontSize: Math.round(tam * 0.38) }
  const imagen = src || (usuario?.tiene_foto ? `/api/usuarios/${usuario.id}/foto` : null)
  return imagen
    ? <img className="avatar-img" style={estilo} src={imagen} alt={usuario?.nombre || ''} />
    : <span className="avatar-ini" style={estilo} aria-hidden="true">{iniciales}</span>
}
