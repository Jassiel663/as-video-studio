'use strict';
/**
 * LAS CUENTAS DE OTRAS PERSONAS (03-10-2026).
 *
 * Cualquiera puede crearse una cuenta en /registro, pero nace PENDIENTE: no
 * entra hasta que la administradora la aprueba en /admin. Hasta que haya
 * creditos, una cuenta aprobada genera con las claves de la instalacion, y por
 * eso cada una lleva un TOPE DE GASTO al mes que pone el admin.
 *
 * CADA CUENTA TIENE SU PROPIO ESTUDIO: un proceso Python con su carpeta de
 * datos (sus estilos, sus videos, sus redes), en el puerto 8200 + id. nginx
 * manda a cada sesion al suyo con la cabecera X-Studio-Port de /api/_auth. La
 * cuenta admin (la de siempre) sigue en el 8110 con los datos de siempre.
 *
 * Crear y parar esos procesos es cosa de root (systemd), y este servicio no
 * puede (NoNewPrivileges). Asi que aqui solo se DEJA UNA PETICION en
 * `<datos>/peticiones/` y la cumple `asvs-cuentas`, que vigila esa carpeta.
 *
 * Y para que el estudio de la cuenta sepa su tope, se le escribe su FICHA en
 * `<datos>/cuentas/<usuario>.json` (la lee con ESTUDIO_CUENTA_FICHA).
 */
const fs = require('fs');
const path = require('path');
const config = require('./config');

const PUERTO_ADMIN = 8110;
const PUERTO_BASE = 8200;
const RESERVADOS = new Set(['admin', 'root', 'estudio', 'studio', 'login', 'registro', 'api', 'mind',
  'soporte', 'support', 'sistema', 'system', 'null', 'undefined', 'www', 'mail']);

const RAIZ = config.raizInstalacion;                    // /opt/as-video-studio
const DATOS_ADMIN = path.join(RAIZ, 'datos');
const CUENTAS = path.join(RAIZ, 'cuentas');
const PETICIONES = path.join(config.dataDir, 'peticiones');
const FICHAS = path.join(config.dataDir, 'cuentas');

function puertoDe(user) {
  if (!user) return 0;
  if (user.role === 'admin') return PUERTO_ADMIN;
  if (user.port) return user.port;
  // LAS CUENTAS DE ANTES (creadas por consola con `bin/user.js`, sin correo):
  // entraban todas al estudio de siempre y lo siguen haciendo.
  if (!user.email && (user.status || 'activa') === 'activa') return PUERTO_ADMIN;
  return 0;
}

/** Comprueba lo que manda /registro. -> {ok, error?, limpio?} */
function validarRegistro(cuerpo) {
  const usuario = String((cuerpo && cuerpo.usuario) || '').trim().toLowerCase();
  const correo = String((cuerpo && cuerpo.correo) || '').trim().toLowerCase();
  const password = String((cuerpo && cuerpo.password) || '');
  const nombre = String((cuerpo && cuerpo.nombre) || '').trim().slice(0, 60);
  if (!/^[a-z0-9_]{3,20}$/.test(usuario)) {
    return { ok: false, error: 'El usuario: de 3 a 20 letras, números o _ (sin espacios ni tildes).' };
  }
  if (RESERVADOS.has(usuario)) return { ok: false, error: 'Ese nombre de usuario no está disponible.' };
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(correo) || correo.length > 120) {
    return { ok: false, error: 'Escribe un correo válido.' };
  }
  if (password.length < 12) return { ok: false, error: 'La contraseña: al menos 12 caracteres.' };
  if (password.length > 200) return { ok: false, error: 'La contraseña es demasiado larga.' };
  if (password.toLowerCase().includes(usuario)) {
    return { ok: false, error: 'La contraseña no puede llevar tu nombre de usuario.' };
  }
  if (!(cuerpo && (cuerpo.acepto === true || cuerpo.acepto === '1' || cuerpo.acepto === 'on'))) {
    return { ok: false, error: 'Tienes que aceptar las condiciones de uso.' };
  }
  return { ok: true, limpio: { usuario, correo, password, nombre: nombre || usuario } };
}

/** Deja una peticion para `asvs-cuentas` (root). -> ruta del fichero */
function pedir(accion, usuario, puerto) {
  if (!['crear', 'parar', 'arrancar', 'borrar'].includes(accion)) throw new Error('accion desconocida');
  if (!/^[a-z0-9_]{3,20}$/.test(usuario)) throw new Error('usuario no valido');
  fs.mkdirSync(PETICIONES, { recursive: true, mode: 0o700 });
  const nombre = `${Date.now()}-${accion}-${usuario}.json`;
  const ruta = path.join(PETICIONES, nombre);
  // el temporal va FUERA de peticiones/: asvs-cuentas.path salta en cuanto esa
  // carpeta no esta vacia, y un .tmp a medias la tendria ocupada para nada
  const temporal = path.join(config.dataDir, `.${nombre}.tmp`);
  fs.writeFileSync(temporal, JSON.stringify({ accion, usuario, puerto: Number(puerto) || 0 }));
  fs.renameSync(temporal, ruta);                       // aparece entera o no aparece
  return ruta;
}

/** Lo que el estudio de la cuenta necesita saber de si misma. */
function escribirFicha(user) {
  fs.mkdirSync(FICHAS, { recursive: true, mode: 0o700 });
  const ficha = {
    usuario: user.username, rol: user.role, estado: user.status || 'activa',
    tope_mes_usd: user.tope_mes_usd == null ? null : Number(user.tope_mes_usd),
  };
  const ruta = path.join(FICHAS, `${user.username}.json`);
  fs.writeFileSync(ruta + '.tmp', JSON.stringify(ficha, null, 2));
  fs.renameSync(ruta + '.tmp', ruta);
}

/** ¿Usa el estudio de siempre (el 8110)? La admin y las cuentas de antes. */
function deLaCasa(user) {
  return puertoDe(user) === PUERTO_ADMIN;
}

function datosDe(user) {
  return deLaCasa(user) ? DATOS_ADMIN : path.join(CUENTAS, user.username, 'datos');
}

/** El estudio de la cuenta, ¿esta montado? (lo deja asvs-cuentas al crear) */
function montada(user) {
  if (deLaCasa(user)) return true;
  return fs.existsSync(path.join(CUENTAS, user.username, 'entorno'));
}

function gastoDelMes(user, mes) {
  const que = mes || new Date().toISOString().slice(0, 7);
  let total = 0;
  try {
    const texto = fs.readFileSync(path.join(datosDe(user), 'coste_global.jsonl'), 'utf8');
    for (const linea of texto.split('\n')) {
      if (!linea.trim()) continue;
      try {
        const d = JSON.parse(linea);
        if (String(d.momento || '').startsWith(que)) total += Number(d.usd) || 0;
      } catch { /* linea rota */ }
    }
  } catch { /* sin gasto */ }
  return Math.round(total * 100) / 100;
}

/** El gasto de los ultimos `dias` dias, dia a dia. -> [{dia, usd}] (el mas antiguo primero) */
function gastoPorDia(user, dias = 14) {
  const hoy = new Date();
  const salida = [];
  const indice = {};
  for (let k = dias - 1; k >= 0; k -= 1) {
    const d = new Date(hoy.getTime() - k * 86400000).toISOString().slice(0, 10);
    indice[d] = salida.length;
    salida.push({ dia: d, usd: 0 });
  }
  try {
    const texto = fs.readFileSync(path.join(datosDe(user), 'coste_global.jsonl'), 'utf8');
    for (const linea of texto.split('\n')) {
      if (!linea.trim()) continue;
      try {
        const d = JSON.parse(linea);
        const dia = String(d.momento || '').slice(0, 10);
        if (dia in indice) salida[indice[dia]].usd += Number(d.usd) || 0;
      } catch { /* linea rota */ }
    }
  } catch { /* sin gasto */ }
  return salida.map((x) => ({ dia: x.dia, usd: Math.round(x.usd * 100) / 100 }));
}

/** Pregunta a SU estudio (el proceso de la cuenta). -> json o null */
async function aSuEstudio(user, metodo, ruta) {
  const puerto = puertoDe(user);
  if (!puerto) return null;
  try {
    const res = await fetch(`http://127.0.0.1:${puerto}${ruta}`, {
      method: metodo, headers: { 'Content-Type': 'application/json' },
      body: metodo === 'GET' ? undefined : '{}', signal: AbortSignal.timeout(8000),
    });
    return await res.json();
  } catch { return null; }
}

/** Los videos de una cuenta, para el panel (moderar). */
function videosDe(user) {
  const carpeta = path.join(datosDe(user), 'proyectos');
  let nombres = [];
  try { nombres = fs.readdirSync(carpeta); } catch { return []; }
  const salida = [];
  for (const pid of nombres) {
    if (!/^[A-Za-z0-9_.-]+$/.test(pid)) continue;
    let ficha = {};
    try { ficha = JSON.parse(fs.readFileSync(path.join(carpeta, pid, 'proyecto.json'), 'utf8')); } catch { continue; }
    const mp4 = mp4De(user, pid);
    salida.push({
      id: pid, nombre: ficha.nombre || pid, creado: ficha.creado || '', actualizado: ficha.actualizado || '',
      short: !!(ficha.short || ficha.short_de), doblaje: ficha.doblaje_idioma || '',
      montado: !!mp4,
    });
  }
  return salida.sort((a, b) => String(b.actualizado).localeCompare(String(a.actualizado)));
}

/** El MP4 mas reciente de un proyecto de la cuenta (con marca si la tiene), o ''. */
function mp4De(user, pid) {
  if (!/^[A-Za-z0-9_.-]+$/.test(String(pid || ''))) return '';
  const render = path.join(datosDe(user), 'proyectos', pid, 'pasos', 'render');
  let versiones = [];
  try {
    versiones = fs.readdirSync(render).filter((n) => /^v\d+$/.test(n))
      .sort((a, b) => Number(b.slice(1)) - Number(a.slice(1)));
  } catch { return ''; }
  for (const v of versiones) {
    for (const nombre of ['video_final.mp4', 'video.mp4']) {
      const ruta = path.join(render, v, nombre);
      if (fs.existsSync(ruta)) return ruta;
    }
  }
  return '';
}

function ocupado(user) {
  let bytes = 0;
  const pila = [datosDe(user)];
  let vistos = 0;
  while (pila.length && vistos < 200000) {
    const actual = pila.pop();
    let entradas = [];
    try { entradas = fs.readdirSync(actual, { withFileTypes: true }); } catch { continue; }
    for (const e of entradas) {
      vistos += 1;
      const ruta = path.join(actual, e.name);
      if (e.isDirectory()) pila.push(ruta);
      else if (e.isFile()) { try { bytes += fs.statSync(ruta).size; } catch { /* nada */ } }
    }
  }
  return Math.round(bytes / 1e6);
}

module.exports = {
  PUERTO_ADMIN, PUERTO_BASE, RESERVADOS, CUENTAS, PETICIONES, FICHAS,
  puertoDe, validarRegistro, pedir, escribirFicha, datosDe, montada, gastoDelMes, videosDe, mp4De, ocupado,
  gastoPorDia, aSuEstudio,
};
