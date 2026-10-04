'use strict';
/**
 * Las cuentas de otras personas, de punta a punta, con el servidor de verdad:
 *
 *     node pruebas/cuentas.js      (necesita node_modules)
 *
 * Arranca server.js en un puerto libre con una base de datos y una
 * instalacion de mentira (carpetas temporales) y recorre: crear cuenta ->
 * pendiente (no entra) -> el admin la aprueba (peticion para asvs-cuentas y
 * ficha con el tope) -> entra con usuario y contrasena -> /_auth da SU puerto
 * (403 mientras su estudio no esta montado) -> el panel ve su gasto y sus
 * videos -> suspendida no pasa. Y lo que NO debe poder hacer nadie.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const RAIZ = fs.mkdtempSync(path.join(os.tmpdir(), 'prueba_cuentas_'));
const DATOS = path.join(RAIZ, 'login', 'datos');
fs.mkdirSync(DATOS, { recursive: true });
const PUERTO = 30000 + Math.floor(Math.random() * 20000);
const BASE = `http://127.0.0.1:${PUERTO}`;

process.env.SESSION_SECRET = 'prueba'.repeat(8);
process.env.DATA_DIR = DATOS;
process.env.RAIZ_INSTALACION = RAIZ;

let fallos = 0;
function ok(que, condicion, detalle) {
  if (!condicion) fallos += 1;
  console.log(`${condicion ? '  ok  ' : ' FALLO'} ${que}${condicion || detalle === undefined ? '' : `  -> ${JSON.stringify(detalle)}`}`);
}

/** Un navegador minimo: guarda la cookie de sesion y el token CSRF. */
function navegador() {
  let cookie = '';
  let csrf = '';
  async function pedir(metodo, ruta, cuerpo, cabeceras) {
    const h = Object.assign({ Accept: 'application/json', Origin: BASE }, cabeceras || {});
    if (cookie) h.Cookie = cookie;
    if (cuerpo !== undefined) { h['Content-Type'] = 'application/json'; h['X-CSRF-Token'] = csrf; }
    const res = await fetch(BASE + ruta, { method: metodo, headers: h, redirect: 'manual',
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo) });
    const nueva = res.headers.get('set-cookie');
    if (nueva) cookie = nueva.split(';')[0];
    let datos = {};
    try { datos = await res.clone().json(); } catch { /* no es json */ }
    return { estado: res.status, datos, cabeceras: res.headers };
  }
  return {
    pedir,
    async token() { csrf = (await pedir('GET', '/api/csrf')).datos.csrfToken; return csrf; },
  };
}

(async () => {
  // la cuenta admin, como la de siempre (sin correo) pero con rol admin
  const { hashPassword } = require('../lib/auth');
  const { stmt, db } = require('../lib/db');
  stmt.insertUser.run({ username: 'estudio', display_name: 'Yo', email: null,
    password_hash: await hashPassword('llave-del-admin-123456'), role: 'admin' });
  // una de antes, sin correo y sin rol: sigue entrando a la de siempre
  stmt.insertUser.run({ username: 'amigo', display_name: null, email: null,
    password_hash: await hashPassword('llave-del-amigo-123456'), role: 'user' });
  db.close();

  const servidor = spawn(process.execPath, [path.join(__dirname, '..', 'server.js')], {
    env: Object.assign({}, process.env, { PORT: String(PUERTO), HOST: '127.0.0.1', SECURE_COOKIES: '0',
      APP_ORIGENES: BASE, NODE_ENV: 'test', TOPE_DEFECTO_USD: '5' }),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let salida = '';
  servidor.stdout.on('data', (d) => { salida += d; });
  servidor.stderr.on('data', (d) => { salida += d; });
  for (let i = 0; i < 50 && !salida.includes('escuchando'); i += 1) await new Promise((r) => setTimeout(r, 100));

  try {
    console.log('-- crear cuenta');
    const ana = navegador();
    await ana.token();
    let r = await ana.pedir('POST', '/api/registro', { usuario: 'ana_v', correo: 'ana@ejemplo.com', password: 'corta', acepto: true });
    ok('contrasena corta: no', r.estado === 400, r.datos);
    r = await ana.pedir('POST', '/api/registro', { usuario: 'admin', correo: 'x@ejemplo.com', password: 'una-buena-llave-1234', acepto: true });
    ok('nombre reservado: no', r.estado === 400, r.datos);
    r = await ana.pedir('POST', '/api/registro', { usuario: 'ana_v', correo: 'ana@ejemplo.com', password: 'una-buena-llave-1234', acepto: false });
    ok('sin aceptar las condiciones: no', r.estado === 400, r.datos);
    r = await ana.pedir('POST', '/api/registro', { usuario: 'Ana_V', correo: 'ANA@ejemplo.com', password: 'una-buena-llave-1234', acepto: true });
    ok('cuenta creada', r.estado === 200 && r.datos.ok, r.datos);
    r = await ana.pedir('POST', '/api/registro', { usuario: 'otra', correo: 'ana@ejemplo.com', password: 'una-buena-llave-1234', acepto: true });
    ok('el mismo correo dos veces: no', r.estado === 409, r.datos);

    console.log('-- pendiente no entra');
    r = await ana.pedir('POST', '/api/login', { usuario: 'ana_v', password: 'una-buena-llave-1234' });
    ok('pendiente: dice que espere la aprobacion', r.estado === 403 && /pendiente/.test(r.datos.error), r.datos);
    r = await ana.pedir('POST', '/api/login', { usuario: 'ana_v', password: 'otra-cosa-que-no-es' });
    ok('contrasena mal: no dice si la cuenta existe', r.estado === 401 && !/pendiente/.test(r.datos.error), r.datos);
    r = await ana.pedir('POST', '/api/login', { password: 'una-buena-llave-1234' });
    ok('solo contrasena NO vale para las cuentas de /registro', r.estado === 401, r.datos);

    console.log('-- el admin');
    const yo = navegador();
    await yo.token();
    r = await yo.pedir('POST', '/api/login', { password: 'llave-del-admin-123456' });
    ok('el admin entra solo con su contrasena, como siempre', r.estado === 200 && r.datos.user.role === 'admin', r.datos);
    await yo.token();
    r = await yo.pedir('GET', '/api/_auth');
    ok('el admin va al 8110 (su estudio de siempre)', r.estado === 200 && r.cabeceras.get('x-studio-port') === '8110', r.estado);
    r = await yo.pedir('GET', '/api/admin/resumen');
    const anaFicha = (r.datos.cuentas || []).find((c) => c.usuario === 'ana_v');
    ok('el panel ve la cuenta pendiente con el tope por defecto', r.datos.pendientes === 1 && anaFicha && anaFicha.tope_mes_usd === 5, r.datos);
    r = await yo.pedir('POST', `/api/admin/cuentas/${anaFicha.id}/aprobar`, {});
    ok('aprobada', r.estado === 200 && r.datos.cuenta.estado === 'activa', r.datos);
    const peticiones = fs.readdirSync(path.join(DATOS, 'peticiones'));
    const peticion = JSON.parse(fs.readFileSync(path.join(DATOS, 'peticiones', peticiones[0]), 'utf8'));
    ok('deja la peticion para asvs-cuentas', peticion.accion === 'crear' && peticion.usuario === 'ana_v' && peticion.puerto === 8200 + anaFicha.id, peticion);
    ok('sin temporales en la carpeta vigilada', peticiones.every((n) => n.endsWith('.json')), peticiones);
    const ficha = JSON.parse(fs.readFileSync(path.join(DATOS, 'cuentas', 'ana_v.json'), 'utf8'));
    ok('escribe su ficha con el tope', ficha.tope_mes_usd === 5 && ficha.estado === 'activa', ficha);
    r = await yo.pedir('PUT', `/api/admin/cuentas/${anaFicha.id}`, { tope_mes_usd: 12, nota: 'amiga de clase' });
    ok('cambiar el tope', r.datos.cuenta.tope_mes_usd === 12
      && JSON.parse(fs.readFileSync(path.join(DATOS, 'cuentas', 'ana_v.json'), 'utf8')).tope_mes_usd === 12, r.datos);

    console.log('-- la cuenta entra a SU estudio');
    await ana.token();
    r = await ana.pedir('POST', '/api/login', { usuario: 'ANA@ejemplo.com', password: 'una-buena-llave-1234' });
    ok('entra con el correo (da igual mayusculas)', r.estado === 200, r.datos);
    r = await ana.pedir('GET', '/api/_auth');
    ok('su estudio aun no esta montado: 403 (pantalla de espera)', r.estado === 403, r.estado);
    const carpeta = path.join(RAIZ, 'cuentas', 'ana_v');
    fs.mkdirSync(path.join(carpeta, 'datos', 'proyectos', 'mi_video', 'pasos', 'render', 'v2'), { recursive: true });
    fs.writeFileSync(path.join(carpeta, 'entorno'), 'PUERTO=1\n');
    fs.writeFileSync(path.join(carpeta, 'datos', 'proyectos', 'mi_video', 'proyecto.json'), JSON.stringify({ nombre: 'Mi vídeo', actualizado: '2026-10-04T10:00:00' }));
    fs.writeFileSync(path.join(carpeta, 'datos', 'proyectos', 'mi_video', 'pasos', 'render', 'v2', 'video_final.mp4'), 'mp4');
    const mes = new Date().toISOString().slice(0, 7);
    fs.writeFileSync(path.join(carpeta, 'datos', 'coste_global.jsonl'),
      `{"usd": 1.5, "momento": "${mes}-02T10:00:00"}\n{"usd": 9, "momento": "2020-01-01T00:00:00"}\n`);
    r = await ana.pedir('GET', '/api/_auth');
    ok('montado: va a SU puerto', r.estado === 200 && r.cabeceras.get('x-studio-port') === String(8200 + anaFicha.id), r.estado);
    r = await ana.pedir('GET', '/api/me');
    ok('/api/me dice que su estudio esta listo', r.datos.estudio && r.datos.estudio.listo === true, r.datos);
    r = await ana.pedir('GET', '/api/admin/resumen');
    ok('una cuenta normal NO ve el panel', r.estado === 403, r.estado);
    await ana.token();
    r = await ana.pedir('POST', `/api/admin/cuentas/${anaFicha.id}/aprobar`, {});
    ok('ni puede aprobar nada', r.estado === 403, r.estado);

    console.log('-- el panel ve lo suyo');
    r = await yo.pedir('GET', '/api/admin/resumen');
    const fichaAna = r.datos.cuentas.find((c) => c.usuario === 'ana_v');
    ok('su gasto de ESTE mes', fichaAna.gasto_mes === 1.5 && fichaAna.videos === 1, fichaAna);
    r = await yo.pedir('GET', `/api/admin/cuentas/${anaFicha.id}/videos`);
    ok('sus videos', r.datos.videos.length === 1 && r.datos.videos[0].montado && r.datos.videos[0].nombre === 'Mi vídeo', r.datos);
    r = await yo.pedir('GET', `/api/admin/cuentas/${anaFicha.id}/videos/mi_video`);
    ok('y el admin puede verlos', r.estado === 200, r.estado);
    r = await yo.pedir('GET', `/api/admin/cuentas/${anaFicha.id}/videos/..%2F..%2Fsecretos`);
    ok('un id con trampa no sale', r.estado === 404, r.estado);

    console.log('-- suspender');
    await yo.token();
    r = await yo.pedir('POST', `/api/admin/cuentas/${anaFicha.id}/suspender`, {});
    ok('suspendida', r.datos.cuenta.estado === 'suspendida', r.datos);
    r = await ana.pedir('GET', '/api/_auth');
    ok('deja de pasar AL MOMENTO (sin esperar a que caduque la sesion)', r.estado === 401, r.estado);
    r = await yo.pedir('POST', `/api/admin/cuentas/1/suspender`, {});
    ok('al admin no se le suspende', r.estado === 400, r.datos);

    console.log('-- las cuentas de antes');
    const amigo = navegador();
    await amigo.token();
    r = await amigo.pedir('POST', '/api/login', { password: 'llave-del-amigo-123456' });
    ok('una cuenta de consola sigue entrando solo con contrasena', r.estado === 200, r.datos);
    r = await amigo.pedir('GET', '/api/_auth');
    ok('y va al estudio de siempre', r.cabeceras.get('x-studio-port') === '8110', r.estado);
  } catch (err) {
    fallos += 1;
    console.log(' FALLO excepcion:', err.stack || err);
  } finally {
    servidor.kill();
    fs.rmSync(RAIZ, { recursive: true, force: true });
  }
  console.log(fallos ? `\nFALLARON ${fallos}` : '\nCUENTAS OK: todas las comprobaciones pasan');
  process.exit(fallos ? 1 : 0);
})();
