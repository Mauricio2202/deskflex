/* Invitación a sala: elegir asiento entre los apartados, con actualización en vivo de los ocupados. */
(() => {
  const root = document.getElementById('inv');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const seats = [...root.querySelectorAll('.seat[role="button"]')];
  const mio0 = Number(root.dataset.mio) || null;
  let sel = mio0;

  function msg(t, tipo) { const m = $('inv-msg'); m.hidden = !t; m.querySelector('span').textContent = t || ''; m.className = 'alert mapmsg alert--' + (tipo || 'info'); }
  function pintar() {
    seats.forEach((s) => {
      const k = Number(s.dataset.asiento), es = sel === k;
      s.dataset.sel = es ? 'true' : 'false'; s.setAttribute('aria-pressed', es);
      s.setAttribute('tabindex', s.dataset.estado === 'libre' || es ? '0' : '-1');
    });
    $('inv-asiento').value = sel || '';
    $('inv-txt').textContent = sel ? (sel === mio0 ? `Tu asiento actual: ${sel}` : `Asiento elegido: ${sel}`) : 'Toca un asiento disponible';
    $('inv-btn').disabled = !sel || sel === mio0;
    const libres = seats.filter((s) => s.dataset.estado === 'libre' && Number(s.dataset.asiento) !== mio0).length;
    $('inv-libres').textContent = `${libres} de ${seats.length} asientos sin elegir`;
  }
  function elegir(s) {
    const k = Number(s.dataset.asiento);
    if (s.dataset.estado === 'ocupado' && k !== mio0) { msg(`El asiento ${k} ya lo eligió otro integrante.`, 'error'); return; }
    msg(''); sel = (sel === k && k !== mio0) ? null : k; pintar();
  }
  seats.forEach((s) => {
    s.addEventListener('click', () => elegir(s));
    s.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); elegir(s); } });
  });

  async function refrescar() {
    try {
      const r = await fetch(root.dataset.api, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!r.ok) return;
      const d = await r.json(), ocupados = new Set(d.tomados);
      seats.forEach((s) => { const k = Number(s.dataset.asiento); s.dataset.estado = ocupados.has(k) ? 'ocupado' : 'libre'; });
      if (sel && sel !== mio0 && ocupados.has(sel)) { msg(`El asiento ${sel} acaba de ser elegido por otro integrante. Elige otro.`, 'error'); sel = null; }
      pintar();
    } catch (e) { /* sin conexión: se reintenta */ }
  }
  setInterval(() => { if (!document.hidden) refrescar(); }, 4000);
  pintar();
})();
