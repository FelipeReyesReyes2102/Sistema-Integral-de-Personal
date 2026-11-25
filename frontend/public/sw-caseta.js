/* Service worker de la app de Caseta (SIP-O).
 * No guarda nada en caché: todo va siempre a la red, para que caseta vea siempre los permisos al día.
 * Solo muestra un aviso claro si el dispositivo se quedó sin conexión a la red interna. */
const SIN_RED = `<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Caseta · sin conexión</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;background:#f4f6fa;color:#1d2433}
.c{max-width:340px;margin:16px;padding:24px;background:#fff;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.08);text-align:center}
h1{font-size:20px;margin:0 0 8px}p{margin:0 0 16px;line-height:1.45;color:#4a5468}
button{font:inherit;font-weight:600;padding:12px 20px;border:0;border-radius:10px;background:#1f4a86;color:#fff}</style></head>
<body><div class="c"><h1>Sin conexión con SIP-O</h1>
<p>El dispositivo no llega al servidor. Revisa que esté conectado al Wi-Fi interno de O-tek y vuelve a intentar.</p>
<button onclick="location.reload()">Reintentar</button></div></body></html>`

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return
  e.respondWith(fetch(e.request).catch(() => new Response(SIN_RED, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })))
})
