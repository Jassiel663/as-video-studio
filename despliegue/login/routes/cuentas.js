'use strict';
/**
 * /api/registro (crear cuenta) y /api/admin/* (el panel del admin).
 * Lo que hay detras de cada cosa esta en lib/cuentas.js.
 */
const express = require('express');
const rateLimit = require('express-rate-limit');

const config = require('../lib/config');
const { hashPassword } = require('../lib/auth');
const { stmt } = require('../lib/db');
const cuentas = require('../lib/cuentas');
const { verifyCsrf } = require('../lib/middleware');

const router = express.Router();
const TOPE_DEFECTO = Number(process.env.TOPE_DEFECTO_USD || 5);
const ESTUDIO_ADMIN = `http://127.0.0.1:${cuentas.PUERTO_ADMIN}`;

/** Un aviso en el estudio del admin (campana y Telegram). Nunca bloquea nada. */
function avisarAdmin(titulo, texto) {
  fetch(`${ESTUDIO_ADMIN}/api/avisos/nuevo`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tipo: 'cuenta', titulo, texto, enlace: config.appUrl ? `${config.appUrl}/admin` : '' }),
    signal: AbortSignal.timeout(5000),
  }).catch(() => { /* sin estudio del admin: el panel lo enseña igual */ });
}

const registroLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  limit: 5,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: { ok: false, error: 'Demasiadas cuentas creadas desde esta conexión. Prueba dentro de una hora.' },
});

function auditar(req, username, userId, reason) {
  try {
    stmt.insertLoginEvent.run({
      username: username || null, user_id: userId || null, ip: req.ip || null,
      user_agent: (req.get('user-agent') || '').slice(0, 300), success: 1, reason,
    });
  } catch { /* la auditoria nunca tumba nada */ }
}

// ------------------------------------------------------------------ registro
router.post('/registro', registroLimiter, verifyCsrf, async (req, res) => {
  if (!config.registroAbierto) {
    return res.status(403).json({ ok: false, error: 'Ahora mismo no se pueden crear cuentas nuevas.' });
  }
  const v = cuentas.validarRegistro(req.body || {});
  if (!v.ok) return res.status(400).json({ ok: false, error: v.error });
  const { usuario, correo, password, nombre } = v.limpio;
  if (stmt.findByUsername.get(usuario)) {
    return res.status(409).json({ ok: false, error: 'Ese nombre de usuario ya existe. Prueba con otro.' });
  }
  if (stmt.findByEmail.get(correo)) {
    return res.status(409).json({ ok: false, error: 'Ya hay una cuenta con ese correo. Entra con ella.' });
  }
  try {
    const hash = await hashPassword(password);
    const r = stmt.insertCuenta.run({ username: usuario, display_name: nombre, email: correo,
      password_hash: hash, tope_mes_usd: TOPE_DEFECTO });
    auditar(req, usuario, r.lastInsertRowid, 'registro');
    avisarAdmin(`👤 Nueva cuenta pendiente: @${usuario}`,
      `${nombre} (${correo}) quiere entrar. Apruébala o recházala en el Panel de admin.`);
  } catch (err) {
    console.error('[registro]', err.message);
    return res.status(500).json({ ok: false, error: 'No se ha podido crear la cuenta. Inténtalo de nuevo.' });
  }
  return res.json({ ok: true,
    mensaje: 'Cuenta creada. Está pendiente de aprobación: cuando el administrador la active podrás entrar.' });
});

// -------------------------------------------------------------------- admin
function requireAdmin(req, res, next) {
  const user = req.session && req.session.userId ? stmt.findById.get(req.session.userId) : null;
  if (!user || user.role !== 'admin' || !user.is_active) {
    return res.status(403).json({ ok: false, error: 'Solo el administrador.' });
  }
  req.admin = user;
  return next();
}

function cuentaDe(req, res) {
  const user = stmt.findById.get(Number(req.params.id));
  if (!user || user.status === 'borrada') {
    res.status(404).json({ ok: false, error: 'Esa cuenta no existe.' });
    return null;
  }
  return user;
}

function ficha(user) {
  return {
    id: user.id, usuario: user.username, nombre: user.display_name || user.username, correo: user.email || '',
    rol: user.role, estado: user.status || 'activa', puerto: cuentas.puertoDe(user),
    estudio_listo: cuentas.montada(user), tope_mes_usd: user.tope_mes_usd, nota: user.nota || '',
    creada: user.created_at, aprobada: user.approved_at || '', ultimo_acceso: user.last_login_at || '',
    gasto_mes: cuentas.gastoDelMes(user),
  };
}

router.get('/admin/resumen', requireAdmin, (req, res) => {
  const lista = stmt.listAll.all().map((u) => {
    const f = ficha(stmt.findById.get(u.id));
    f.videos = cuentas.videosDe(stmt.findById.get(u.id)).length;
    return f;
  });
  res.json({
    ok: true, cuentas: lista,
    pendientes: lista.filter((c) => c.estado === 'pendiente').length,
    gasto_mes_total: Math.round(lista.reduce((t, c) => t + c.gasto_mes, 0) * 100) / 100,
    registro_abierto: config.registroAbierto,
    eventos: stmt.recentEvents.all(40),
  });
});

router.post('/admin/cuentas/:id/:accion', requireAdmin, verifyCsrf, (req, res) => {
  const user = cuentaDe(req, res);
  if (!user) return undefined;
  const accion = req.params.accion;
  if (user.id === req.admin.id || user.role === 'admin') {
    return res.status(400).json({ ok: false, error: 'A la cuenta del administrador no se le hace eso.' });
  }
  try {
    if (accion === 'aprobar') {
      const puerto = cuentas.PUERTO_BASE + user.id;
      stmt.approve.run({ id: user.id, port: puerto });
      cuentas.escribirFicha(stmt.findById.get(user.id));
      cuentas.pedir('crear', user.username, puerto);
    } else if (accion === 'suspender') {
      stmt.setStatus.run({ id: user.id, status: 'suspendida', is_active: 0 });
      cuentas.escribirFicha(stmt.findById.get(user.id));
      if (user.port) cuentas.pedir('parar', user.username, user.port);
    } else if (accion === 'reactivar') {
      if (!user.port) return res.status(400).json({ ok: false, error: 'Esa cuenta nunca se aprobó: apruébala.' });
      stmt.setStatus.run({ id: user.id, status: 'activa', is_active: 1 });
      cuentas.escribirFicha(stmt.findById.get(user.id));
      cuentas.pedir('arrancar', user.username, user.port);
    } else if (accion === 'borrar') {
      stmt.setStatus.run({ id: user.id, status: 'borrada', is_active: 0 });
      if (user.port) cuentas.pedir('borrar', user.username, user.port);
    } else {
      return res.status(404).json({ ok: false, error: 'Acción desconocida.' });
    }
  } catch (err) {
    console.error('[admin]', err.message);
    return res.status(500).json({ ok: false, error: `No se ha podido: ${err.message}` });
  }
  auditar(req, req.admin.username, req.admin.id, `admin_${accion}:${user.username}`);
  return res.json({ ok: true, cuenta: user.status === 'borrada' ? null : ficha(stmt.findById.get(user.id)) });
});

router.put('/admin/cuentas/:id', requireAdmin, verifyCsrf, (req, res) => {
  const user = cuentaDe(req, res);
  if (!user) return undefined;
  const cuerpo = req.body || {};
  if ('tope_mes_usd' in cuerpo) {
    const tope = cuerpo.tope_mes_usd === null || cuerpo.tope_mes_usd === '' ? null : Number(cuerpo.tope_mes_usd);
    if (tope !== null && (!Number.isFinite(tope) || tope < 0 || tope > 100000)) {
      return res.status(400).json({ ok: false, error: 'El tope es un número de dólares (o vacío: sin tope).' });
    }
    stmt.setTope.run(tope, user.id);
  }
  if ('nota' in cuerpo) stmt.setNota.run(String(cuerpo.nota || '').slice(0, 500), user.id);
  const fresca = stmt.findById.get(user.id);
  if (fresca.role !== 'admin' && fresca.status !== 'pendiente') cuentas.escribirFicha(fresca);
  return res.json({ ok: true, cuenta: ficha(fresca) });
});

router.get('/admin/cuentas/:id/videos', requireAdmin, (req, res) => {
  const user = cuentaDe(req, res);
  if (!user) return undefined;
  return res.json({ ok: true, cuenta: ficha(user), videos: cuentas.videosDe(user), ocupado_mb: cuentas.ocupado(user) });
});

// LO QUE ESTA HACIENDO: sus trabajos (preguntados a SU estudio) y su gasto dia a dia.
router.get('/admin/cuentas/:id/actividad', requireAdmin, async (req, res) => {
  const user = cuentaDe(req, res);
  if (!user) return undefined;
  const r = await cuentas.aSuEstudio(user, 'GET', '/api/trabajos');
  const trabajos = ((r && r.trabajos) || []).slice(-15).reverse().map((t) => ({
    id: t.id, nombre: t.nombre, proyecto: t.proyecto, estado: t.estado,
    progreso: t.progreso, mensaje: String(t.mensaje || '').slice(0, 140), creado: t.creado || t.inicio || '',
  }));
  return res.json({ ok: true, estudio_responde: !!r, trabajos, gasto_dias: cuentas.gastoPorDia(user, 14) });
});

router.post('/admin/cuentas/:id/trabajos/:tid/cancelar', requireAdmin, verifyCsrf, async (req, res) => {
  const user = cuentaDe(req, res);
  if (!user) return undefined;
  if (!/^[A-Za-z0-9_-]{4,64}$/.test(req.params.tid)) return res.status(400).json({ ok: false, error: 'Trabajo no válido.' });
  const r = await cuentas.aSuEstudio(user, 'POST', `/api/trabajos/${req.params.tid}/cancelar`);
  if (!r) return res.status(502).json({ ok: false, error: 'Su estudio no contesta.' });
  auditar(req, req.admin.username, req.admin.id, `admin_cancelar:${user.username}`);
  return res.json({ ok: true, resultado: r });
});

// LA REVISION DEL CONTENIDO: la hace el estudio del admin (pasos/moderacion.py);
// aqui solo se le pregunta y se le pasan las ordenes.
async function alEstudioAdmin(metodo, ruta, cuerpo) {
  const res = await fetch(`${ESTUDIO_ADMIN}${ruta}`, {
    method: metodo, headers: { 'Content-Type': 'application/json' },
    body: metodo === 'GET' ? undefined : JSON.stringify(cuerpo || {}), signal: AbortSignal.timeout(10000),
  });
  return res.json();
}

router.get('/admin/moderacion', requireAdmin, async (req, res) => {
  try { return res.json(Object.assign({ ok: true }, await alEstudioAdmin('GET', '/api/moderacion'))); }
  catch { return res.status(502).json({ ok: false, error: 'Tu estudio no contesta.' }); }
});

router.post('/admin/moderacion/:accion', requireAdmin, verifyCsrf, async (req, res) => {
  const accion = req.params.accion;
  if (!['revisar', 'visto'].includes(accion)) return res.status(404).json({ ok: false, error: 'Acción desconocida.' });
  try { return res.json(Object.assign({ ok: true }, await alEstudioAdmin('POST', `/api/moderacion/${accion}`, req.body))); }
  catch { return res.status(502).json({ ok: false, error: 'Tu estudio no contesta.' }); }
});

router.get('/admin/cuentas/:id/videos/:pid', requireAdmin, (req, res) => {
  const user = cuentaDe(req, res);
  if (!user) return undefined;
  const ruta = cuentas.mp4De(user, req.params.pid);
  if (!ruta) return res.status(404).json({ ok: false, error: 'Ese vídeo no está montado.' });
  return res.sendFile(ruta, { headers: { 'Cache-Control': 'private, no-store' } });
});

module.exports = { router, requireAdmin };
