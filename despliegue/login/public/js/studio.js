/* Mind Videos — esperando a que el estudio de la cuenta este listo. */
(function () {
  'use strict';

  const logout = document.getElementById('logout');
  const titulo = document.getElementById('titulo');
  const texto = document.getElementById('texto');
  let intentos = 0;

  async function mirar() {
    intentos += 1;
    try {
      const res = await fetch('/api/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (res.status === 401) { window.location.assign('/login'); return; }
      const data = await res.json();
      if (data.ok && data.estudio && data.estudio.listo) { window.location.assign('/'); return; }
    } catch { /* sin red: se reintenta */ }
    if (intentos === 24) {
      titulo.textContent = 'Sigue preparándose…';
      texto.textContent = 'Está tardando más de lo normal. Si en unos minutos no entras, avisa al administrador.';
    }
    setTimeout(mirar, 5000);
  }

  logout.addEventListener('click', async () => {
    logout.disabled = true;
    try {
      const token = (await (await fetch('/api/csrf', { credentials: 'same-origin' })).json()).csrfToken;
      await fetch('/api/logout', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token || '' } });
    } catch { /* se sale igual */ }
    window.location.assign('/login');
  });

  mirar();
})();
