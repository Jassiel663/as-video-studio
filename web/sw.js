/* El service worker de la app instalable (Mind Videos).
 *
 * NO guarda la pagina para usarla sin conexion: el estudio vive en el servidor
 * y una copia vieja de app.js enseñaria datos que ya no son. Lo unico que hace
 * es lo que el navegador exige para poder INSTALAR la app, y si no hay red
 * enseña un aviso en vez de la pantalla de error del navegador. */
const AVISO = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
  + '<title>Mind Videos</title><body style="background:#000;color:#fff;font-family:system-ui;display:grid;'
  + 'place-items:center;height:100vh;margin:0;text-align:center"><div><h2>Sin conexión</h2>'
  + '<p style="color:#aaa">Mind Videos necesita internet. Tus vídeos siguen haciéndose en el servidor.</p>'
  + '<button onclick="location.reload()" style="padding:10px 18px;border-radius:10px;border:0;background:#a78bfa;'
  + 'color:#000;font-weight:700">Reintentar</button></div>';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', ev => ev.waitUntil(self.clients.claim()));
self.addEventListener('fetch', ev => {
  if (ev.request.mode !== 'navigate') return;          // lo demas, como siempre
  ev.respondWith(fetch(ev.request).catch(() =>
    new Response(AVISO, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
