/* Mind Videos — el panel del admin (routes/cuentas.js). */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const estado = { datos: null, filtro: 'todas', abiertas: {}, videos: {}, csrf: null };

  function el(tag, props, ...hijos) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'clase') n.className = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else if (k === 'value') n.value = v;
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const h of hijos.flat()) {
      if (h === null || h === undefined || h === false) continue;
      n.appendChild(typeof h === 'string' || typeof h === 'number' ? document.createTextNode(String(h)) : h);
    }
    return n;
  }

  function fecha(iso) {
    if (!iso) return '—';
    const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z');
    return isNaN(d.getTime()) ? '—' : d.toLocaleString('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  }
  const dolares = (n) => `${Number(n || 0).toFixed(2)} $`;

  function error(texto) {
    $('errorText').textContent = texto || '';
    $('error').classList.toggle('is-visible', !!texto);
  }

  async function csrf() {
    if (!estado.csrf) estado.csrf = (await (await fetch('/api/csrf', { credentials: 'same-origin' })).json()).csrfToken;
    return estado.csrf;
  }

  async function api(metodo, ruta, cuerpo) {
    const opciones = { method: metodo, credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (metodo !== 'GET') {
      opciones.headers['Content-Type'] = 'application/json';
      opciones.headers['X-CSRF-Token'] = await csrf();
      opciones.body = JSON.stringify(cuerpo || {});
    }
    const res = await fetch(ruta, opciones);
    if (res.status === 401) { window.location.assign('/login'); throw new Error('sin sesión'); }
    const datos = await res.json().catch(() => ({}));
    if (!res.ok || datos.ok === false) throw new Error(datos.error || `error ${res.status}`);
    return datos;
  }

  async function cargar() {
    try {
      estado.datos = await api('GET', '/api/admin/resumen');
      error('');
      pintar();
    } catch (e) { error(e.message); }
  }

  async function accion(c, que) {
    const preguntas = {
      aprobar: `¿Aprobar la cuenta de «${c.usuario}»? Se le monta su estudio y podrá generar con tus claves (con un tope de ${c.tope_mes_usd ?? '—'} $ al mes).`,
      suspender: `¿Suspender a «${c.usuario}»? No podrá entrar hasta que la reactives. Sus vídeos se conservan.`,
      reactivar: `¿Reactivar a «${c.usuario}»?`,
      borrar: `¿Borrar la cuenta de «${c.usuario}»? No podrá volver a entrar. Su carpeta se aparta (no se destruye) por si hiciera falta.`,
    };
    if (!window.confirm(preguntas[que] || '¿Seguro?')) return;
    try {
      await api('POST', `/api/admin/cuentas/${c.id}/${que}`);
      await cargar();
    } catch (e) { error(e.message); }
  }

  async function guardar(c, cambios) {
    try {
      await api('PUT', `/api/admin/cuentas/${c.id}`, cambios);
      await cargar();
    } catch (e) { error(e.message); }
  }

  async function verVideos(c) {
    estado.abiertas[c.id] = !estado.abiertas[c.id];
    if (estado.abiertas[c.id]) {
      estado.videos[c.id] = { cargando: true };
      pintar();
      try { estado.videos[c.id] = await api('GET', `/api/admin/cuentas/${c.id}/videos`); }
      catch (e) { estado.videos[c.id] = { error: e.message }; }
    }
    pintar();
  }

  function cifras(d) {
    const activas = d.cuentas.filter((c) => c.estado === 'activa').length;
    const caja = $('cifras');
    caja.replaceChildren(
      el('div', { clase: 'adm-cifra' }, el('b', {}, String(d.cuentas.length)), el('span', {}, 'cuentas')),
      el('div', { clase: 'adm-cifra' }, el('b', {}, String(activas)), el('span', {}, 'activas')),
      el('div', { clase: 'adm-cifra' + (d.pendientes ? ' aviso' : '') }, el('b', {}, String(d.pendientes)), el('span', {}, 'pendientes de aprobar')),
      el('div', { clase: 'adm-cifra' }, el('b', {}, dolares(d.gasto_mes_total)), el('span', {}, 'gastado este mes (todas)')),
    );
  }

  function filtros(d) {
    const opciones = [['todas', 'Todas'], ['pendiente', `Pendientes (${d.pendientes})`], ['activa', 'Activas'], ['suspendida', 'Suspendidas']];
    $('filtros').replaceChildren(...opciones.map(([id, t]) => el('button', {
      clase: 'adm-chip' + (estado.filtro === id ? ' activo' : ''),
      onclick: () => { estado.filtro = id; pintar(); },
    }, t)));
  }

  function tarjeta(c) {
    const tope = c.tope_mes_usd;
    const pasado = tope !== null && tope !== undefined && c.gasto_mes >= tope;
    const campoTope = el('input', { type: 'number', min: '0', step: '1', value: tope ?? '', placeholder: 'sin tope', clase: 'adm-num' });
    const campoNota = el('input', { type: 'text', value: c.nota || '', placeholder: 'nota privada (solo la ves tú)', clase: 'adm-nota', maxlength: '500' });
    const esAdmin = c.rol === 'admin';
    const tarjetaEl = el('article', { clase: `adm-cuenta ${c.estado}` },
      el('div', { clase: 'adm-cab' },
        el('span', { clase: 'adm-avatar' }, (c.nombre || c.usuario || '?').charAt(0).toUpperCase()),
        el('div', { clase: 'adm-crece' },
          el('b', {}, c.nombre || c.usuario, esAdmin ? el('span', { clase: 'adm-sello admin' }, 'ADMIN') : null),
          el('small', {}, `@${c.usuario}` + (c.correo ? ` · ${c.correo}` : ''))),
        el('span', { clase: `adm-sello ${c.estado}` }, {
          pendiente: '⏳ pendiente', activa: '● activa', suspendida: '⏸ suspendida' }[c.estado] || c.estado)),
      el('div', { clase: 'adm-datos' },
        el('span', {}, `Creada ${fecha(c.creada)}`),
        el('span', {}, `Último acceso ${fecha(c.ultimo_acceso)}`),
        el('span', { clase: pasado ? 'pasado' : '' }, `Gastado este mes: ${dolares(c.gasto_mes)}` + (tope !== null && tope !== undefined ? ` de ${dolares(tope)}` : '')),
        el('span', {}, `${c.videos} vídeos`),
        c.estado === 'activa' && !c.estudio_listo ? el('span', { clase: 'pasado' }, 'montando su estudio…') : null),
      esAdmin ? null : el('div', { clase: 'adm-fila' },
        el('label', {}, 'Tope al mes ($)'), campoTope,
        el('button', { clase: 'adm-boton', onclick: () => guardar(c, { tope_mes_usd: campoTope.value === '' ? null : Number(campoTope.value) }) }, 'Guardar tope'),
        campoNota,
        el('button', { clase: 'adm-boton', onclick: () => guardar(c, { nota: campoNota.value }) }, 'Guardar nota')),
      el('div', { clase: 'adm-fila' },
        el('button', { clase: 'adm-boton', onclick: () => verVideos(c) }, estado.abiertas[c.id] ? 'Ocultar vídeos' : '🎬 Ver sus vídeos'),
        el('span', { clase: 'adm-crece' }),
        !esAdmin && c.estado === 'pendiente' ? el('button', { clase: 'adm-boton primario', onclick: () => accion(c, 'aprobar') }, '✓ Aprobar') : null,
        !esAdmin && c.estado === 'pendiente' ? el('button', { clase: 'adm-boton peligro', onclick: () => accion(c, 'borrar') }, 'Rechazar') : null,
        !esAdmin && c.estado === 'activa' ? el('button', { clase: 'adm-boton peligro', onclick: () => accion(c, 'suspender') }, 'Suspender') : null,
        !esAdmin && c.estado === 'suspendida' ? el('button', { clase: 'adm-boton primario', onclick: () => accion(c, 'reactivar') }, 'Reactivar') : null,
        !esAdmin && c.estado === 'suspendida' ? el('button', { clase: 'adm-boton peligro', onclick: () => accion(c, 'borrar') }, 'Borrar') : null));
    if (estado.abiertas[c.id]) {
      const v = estado.videos[c.id] || {};
      const caja = el('div', { clase: 'adm-videos' });
      if (v.cargando) caja.appendChild(el('p', { clase: 'adm-sub' }, 'cargando…'));
      else if (v.error) caja.appendChild(el('p', { clase: 'adm-sub' }, v.error));
      else {
        caja.appendChild(el('p', { clase: 'adm-sub' }, `${(v.videos || []).length} vídeos · ${v.ocupado_mb} MB en disco`));
        (v.videos || []).forEach((x) => caja.appendChild(el('div', { clase: 'adm-video' },
          x.montado ? el('video', { src: `/api/admin/cuentas/${c.id}/videos/${encodeURIComponent(x.id)}`, controls: true, preload: 'none' })
            : el('div', { clase: 'adm-sin' }, 'sin montar'),
          el('div', {}, el('b', {}, x.nombre), el('small', {}, `${x.short ? 'short · ' : ''}${x.doblaje ? `doblaje ${x.doblaje} · ` : ''}${fecha(x.actualizado)}`)))));
      }
      tarjetaEl.appendChild(caja);
    }
    return tarjetaEl;
  }

  function eventos(d) {
    const tabla = $('eventos');
    tabla.replaceChildren(
      el('tr', {}, el('th', {}, 'Cuándo'), el('th', {}, 'Cuenta'), el('th', {}, 'Qué'), el('th', {}, 'IP')),
      ...(d.eventos || []).map((e) => el('tr', { clase: e.success ? '' : 'fallo' },
        el('td', {}, fecha(e.at)), el('td', {}, e.username || '—'),
        el('td', {}, ({ ok: 'entró', registro: 'creó su cuenta', pendiente: 'intentó entrar (pendiente)',
          suspendida: 'intentó entrar (suspendida)', usuario_o_password: 'contraseña mal',
          password_incorrecta: 'contraseña mal', cuenta_bloqueada: 'bloqueada por intentos' })[e.reason]
          || String(e.reason || '').replace('admin_', 'admin: ')),
        el('td', {}, e.ip || '—'))));
  }

  function pintar() {
    const d = estado.datos;
    if (!d) return;
    cifras(d);
    filtros(d);
    const lista = d.cuentas.filter((c) => estado.filtro === 'todas' || c.estado === estado.filtro);
    $('cuentas').replaceChildren(...(lista.length ? lista.map(tarjeta) : [el('p', { clase: 'adm-sub' }, 'Ninguna cuenta aquí.')]));
    eventos(d);
  }

  cargar();
  setInterval(() => { if (!document.hidden && !document.querySelector('.adm-cuenta input:focus')) cargar(); }, 30000);
})();
