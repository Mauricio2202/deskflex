/* Pago: cuenta regresiva de 3 min, formato de tarjeta y reconocimiento de red y banco por los primeros dígitos. */
(() => {
  const form = document.getElementById('pago-form');
  if (!form) return;
  const $ = (id) => document.getElementById(id);

  /* ---- Cuenta regresiva (el servidor decide el plazo real; esto solo lo muestra) ---- */
  const timer = $('pago-timer');
  let resta = Number(timer.dataset.seg), total = Number(timer.dataset.total) || 180;
  const fin = Date.now() + resta * 1000;
  function tick() {
    resta = Math.max(0, Math.round((fin - Date.now()) / 1000));
    $('timer-txt').textContent = `${Math.floor(resta / 60)}:${String(resta % 60).padStart(2, '0')}`;
    $('timer-bar').style.width = `${Math.min(100, (resta / total) * 100)}%`;
    timer.classList.toggle('is-low', resta <= 60);
    if (resta <= 0) {
      clearInterval(iv);
      timer.classList.add('is-over');
      $('timer-msg').textContent = 'El tiempo terminó. Liberamos el lugar: te llevamos de vuelta a reservar.';
      form.querySelectorAll('input,button').forEach((x) => { x.disabled = true; });
      setTimeout(() => { location.reload(); }, 2500);   // el servidor mostrará que expiró y redirigirá
    }
  }
  const iv = setInterval(tick, 1000); tick();

  /* ---- Formato y reconocimiento ---- */
  const num = $('numero'), cvv = $('cvv'), venc = $('vencimiento'), nom = $('titular');
  const red = (d) => /^4/.test(d) ? 'visa' : /^(5[1-5]|2(2[2-9][1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720))/.test(d) ? 'mastercard' : /^3[47]/.test(d) ? 'amex' : null;
  const NOMBRES = { visa: 'VISA', mastercard: 'Mastercard', amex: 'American Express' };
  const luhn = (s) => { let t = 0, alt = false; for (let i = s.length - 1; i >= 0; i--) { let d = +s[i]; if (alt) { d *= 2; if (d > 9) d -= 9; } t += d; alt = !alt; } return t % 10 === 0; };
  let bancoPrev = '', ultimaBin = '', ctl = null;

  function marcas(redId, bancoId) {
    document.querySelectorAll('#marcas .marca').forEach((li) => {
      const on = li.dataset.marca === redId || li.dataset.marca === bancoId;
      li.dataset.on = on ? 'true' : 'false';
    });
    document.getElementById('marcas').classList.toggle('has-active', !!(redId || bancoId));
  }
  async function banco(bin) {
    if (bin === ultimaBin) return; ultimaBin = bin;
    if (bin.length < 6) { bancoPrev = ''; $('cf-banco').textContent = ''; marcas(red(bin), null); return; }
    if (ctl) ctl.abort(); ctl = new AbortController();
    try {
      const r = await fetch(`${form.dataset.bin}?b=${bin}`, { signal: ctl.signal, credentials: 'same-origin' });
      if (!r.ok) return;
      const d = await r.json();
      bancoPrev = d.banco || '';
      $('cf-banco').textContent = bancoPrev;
      marcas(d.red, d.banco_id);
    } catch (e) { /* sin red: se sigue reconociendo la tarjeta por sus primeros dígitos */ }
  }
  num.addEventListener('input', () => {
    let d = num.value.replace(/\D/g, '').slice(0, 19);
    const r = red(d), amex = r === 'amex';
    d = d.slice(0, amex ? 15 : 16);
    num.value = amex ? [d.slice(0, 4), d.slice(4, 10), d.slice(10)].filter(Boolean).join(' ') : d.replace(/(.{4})/g, '$1 ').trim();
    cvv.maxLength = amex ? 4 : 3; cvv.placeholder = amex ? '••••' : '•••';
    $('cf-red').textContent = r ? NOMBRES[r] : 'Tarjeta';
    const base = amex ? '•••• •••••• •••••' : '•••• •••• •••• ••••';
    $('cf-num').textContent = d ? (num.value + base.slice(num.value.length)) : base;
    marcas(r, null); banco(d.slice(0, 6));
    const h = $('numero-hint'), largo = amex ? 15 : 16;
    if (!d) h.textContent = '';
    else if (!r) h.textContent = 'Aceptamos VISA, Mastercard y American Express.';
    else if (d.length < largo) h.textContent = `${NOMBRES[r]}${bancoPrev ? ' · ' + bancoPrev : ''}`;
    else h.textContent = luhn(d) ? `${NOMBRES[r]}${bancoPrev ? ' · ' + bancoPrev : ''} · número válido` : 'El número no parece válido. Revísalo.';
  });
  venc.addEventListener('input', () => {
    let d = venc.value.replace(/\D/g, '').slice(0, 4);
    if (d.length >= 3) d = d.slice(0, 2) + '/' + d.slice(2);
    venc.value = d; $('cf-venc').textContent = d || 'MM/AA';
  });
  nom.addEventListener('input', () => { $('cf-nombre').textContent = nom.value.toUpperCase() || 'NOMBRE DEL TITULAR'; });
  cvv.addEventListener('input', () => { cvv.value = cvv.value.replace(/\D/g, ''); });
  nom.dispatchEvent(new Event('input'));
  form.addEventListener('submit', (e) => { if (resta <= 0) e.preventDefault(); });
  // El número y el CVV no se conservan si la persona regresa con el botón «atrás»
  window.addEventListener('pageshow', (e) => { if (e.persisted) { num.value = ''; cvv.value = ''; } });
})();
