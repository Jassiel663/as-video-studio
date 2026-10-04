/* Mind Videos — crear cuenta (nace pendiente de aprobar: routes/cuentas.js). */
(function () {
  'use strict';

  const form = document.getElementById('registroForm');
  const submit = document.getElementById('submit');
  const submitText = document.getElementById('submitText');
  const errorBox = document.getElementById('error');
  const errorText = document.getElementById('errorText');
  const hecho = document.getElementById('hecho');
  const hechoTexto = document.getElementById('hechoTexto');
  const campo = (id) => document.getElementById(id);
  let csrfToken = null;

  async function fetchCsrf() {
    try {
      const res = await fetch('/api/csrf', { credentials: 'same-origin' });
      csrfToken = (await res.json()).csrfToken || null;
    } catch { csrfToken = null; }
    return csrfToken;
  }
  fetchCsrf();

  function showError(texto) { errorText.textContent = texto; errorBox.classList.add('is-visible'); }
  function clearError() { errorBox.classList.remove('is-visible'); }
  form.addEventListener('input', clearError);
  campo('usuario').addEventListener('input', (ev) => {
    ev.target.value = ev.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '');
  });

  function enviar(cuerpo) {
    return fetch('/api/registro', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken || '' },
      body: JSON.stringify(cuerpo),
    });
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    clearError();
    const cuerpo = {
      nombre: campo('nombre').value.trim(), usuario: campo('usuario').value.trim(),
      correo: campo('correo').value.trim(), password: campo('password').value,
      acepto: campo('acepto').checked,
    };
    if (!/^[a-z0-9_]{3,20}$/.test(cuerpo.usuario)) { showError('El usuario: de 3 a 20 letras, números o _.'); return; }
    if (!cuerpo.correo.includes('@')) { showError('Escribe tu correo.'); return; }
    if (cuerpo.password.length < 12) { showError('La contraseña: al menos 12 caracteres.'); return; }
    if (cuerpo.password !== campo('password2').value) { showError('Las dos contraseñas no coinciden.'); return; }
    if (!cuerpo.acepto) { showError('Tienes que aceptar las condiciones.'); return; }
    submit.disabled = true;
    submitText.textContent = 'Creando…';
    try {
      if (!csrfToken) await fetchCsrf();
      let res = await enviar(cuerpo);
      if (res.status === 403) {
        const previo = await res.clone().json().catch(() => ({}));
        if (String(previo.error || '').includes('Token')) {      // token caducado: otro y otra vez
          await fetchCsrf();
          res = await enviar(cuerpo);
        }
      }
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        form.classList.add('is-hidden');
        hechoTexto.textContent = data.mensaje || 'Cuenta creada.';
        hecho.classList.remove('is-hidden');
        return;
      }
      showError(data.error || 'No se ha podido crear la cuenta.');
    } catch {
      showError('No hay conexión con el servidor. Inténtalo de nuevo.');
    } finally {
      submit.disabled = false;
      submitText.textContent = 'Crear cuenta';
    }
  });
})();
