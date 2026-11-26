/**
 * Funciones del teléfono para la app de Caseta (Android con Capacitor).
 *
 * La app nativa carga SIP-O desde el servidor; Capacitor inyecta su puente, así que este mismo código decide en
 * tiempo de ejecución si usa la cámara y los avisos nativos o los del navegador.
 */
import { Capacitor, registerPlugin } from '@capacitor/core'

export const esNativo = () => {
  try { return Capacitor.isNativePlatform() } catch { return false }
}

/** Servicio nativo de avisos (android-caseta: CasetaAvisosPlugin): revisa SIP-O cada minuto aunque la app esté en segundo plano. */
const CasetaAvisos = registerPlugin('CasetaAvisos')

export async function iniciarAvisosNativos() {
  if (!esNativo()) return false
  try {
    await CasetaAvisos.iniciar({ url: `${window.location.origin}/api/caseta/avisos` })
    return true
  } catch {
    return false
  }
}

export async function detenerAvisosNativos() {
  if (!esNativo()) return
  try { await CasetaAvisos.detener() } catch { /* sin servicio */ }
}

/**
 * Escanea un código con la cámara. formato: 'qr' (gafete del empleado) o 'barras' (etiqueta del equipo).
 * Devuelve el texto leído, null si se canceló, o lanza un Error con un mensaje para el usuario.
 */
export async function escanearNativo(formato) {
  const { BarcodeScanner, BarcodeFormat } = await import('@capacitor-mlkit/barcode-scanning')
  const permiso = await BarcodeScanner.requestPermissions()
  if (permiso.camera !== 'granted' && permiso.camera !== 'limited') {
    throw new Error('Permite el uso de la cámara a la app de Caseta (Ajustes → Aplicaciones → SIP-O Caseta → Permisos).')
  }
  const formats = formato === 'qr'
    ? [BarcodeFormat.QrCode]
    : [BarcodeFormat.Code128, BarcodeFormat.Code39, BarcodeFormat.Code93, BarcodeFormat.Ean13, BarcodeFormat.Ean8,
      BarcodeFormat.UpcA, BarcodeFormat.UpcE, BarcodeFormat.Itf, BarcodeFormat.Codabar, BarcodeFormat.DataMatrix, BarcodeFormat.QrCode]
  // scan() abre el lector de Google (ML Kit); si el módulo aún no está en el teléfono, se descarga una vez.
  try {
    const { available } = await BarcodeScanner.isGoogleBarcodeScannerModuleAvailable()
    if (!available) {
      await BarcodeScanner.installGoogleBarcodeScannerModule()
      throw new Error('Se está instalando el lector de códigos en el teléfono. Intenta de nuevo en unos segundos.')
    }
  } catch (e) {
    if (e?.message?.startsWith('Se está instalando')) throw e
  }
  try {
    const { barcodes } = await BarcodeScanner.scan({ formats })
    return barcodes?.[0]?.rawValue || null
  } catch (e) {
    if (/cancel/i.test(e?.message || '')) return null
    throw new Error(`No se pudo leer el código: ${e?.message || e}`)
  }
}
