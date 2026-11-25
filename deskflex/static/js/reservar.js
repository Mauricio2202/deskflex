/* Reservar: calendario → horario → mapa en vivo. Escritorios por persona; salas de juntas solo para equipos. */
(() => {
  const form = document.getElementById('booking-form');
  if (!form) return;
  const D = form.dataset;
  const CERRADOS = JSON.parse(D.cerrados || '[]');
  const MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
  const $ = (id) => document.getElementById(id);
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
  const fmtH = (h) => `${(h % 12) || 12}:00 ${h < 12 ? 'am' : 'pm'}`;
  const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };

  // esp: número del espacio; equipo: integrantes (solo salas de juntas, que se apartan completas)
  const st = { fecha: D.inicial, modo: 'hora', a: null, b: null, esp: null, equipo: null,
               horas: [], estados: null, precios: {}, ventana: null, vista: parse(D.inicial), firma: null };
  const plano = form.querySelector('.plano');
  const sps = [...plano.querySelectorAll('.sp')];
  const spBy = (n) => sps.find((g) => Number(g.dataset.num) === n);
  const MIN = Number(D.minEquipo || 4);
  let ctl = null;

  /* ---- Calendario ---- */
  function drawCal() {
    const y = st.vista.getFullYear(), m = st.vista.getMonth();
    $('cal-title').textContent = `${MESES[m]} ${y}`;
    const grid = $('cal-grid'); grid.innerHTML = '';
    grid.classList.remove('swap'); void grid.offsetWidth; grid.classList.add('swap');
    ['L','M','M','J','V','S','D'].forEach((l) => {
      const e = document.createElement('div'); e.className = 'dow'; e.textContent = l; e.setAttribute('aria-hidden', 'true'); grid.appendChild(e);
    });
    const first = (new Date(y, m, 1).getDay() + 6) % 7;
    for (let i = 0; i < first; i++) grid.appendChild(document.createElement('span'));
    const n = new Date(y, m + 1, 0).getDate();
    for (let d = 1; d <= n; d++) {
      const f = iso(y, m, d), dow = (new Date(y, m, d).getDay() + 6) % 7;
      const b = document.createElement('button'); b.type = 'button'; b.className = 'cal-day'; b.textContent = d;
      b.disabled = f < D.hoy || f > D.max || CERRADOS.includes(dow);
      if (f === D.hoy) b.classList.add('is-today');
      b.setAttribute('aria-pressed', f === st.fecha ? 'true' : 'false');
      b.setAttribute('aria-label', parse(f).toLocaleDateString('es-MX', { weekday: 'long', day: 'numeric', month: 'long' }) + (b.disabled ? ' (no disponible)' : ''));
      b.addEventListener('click', () => {
        st.fecha = f; st.a = st.b = null; clearSel();
        grid.querySelectorAll('.cal-day').forEach((x) => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', 'true');
        refresh();
      });
      grid.appendChild(b);
    }
    $('cal-prev').disabled = (y === parse(D.hoy).getFullYear() && m <= parse(D.hoy).getMonth());
    const mx = parse(D.max); $('cal-next').disabled = (y > mx.getFullYear()) || (y === mx.getFullYear() && m >= mx.getMonth());
  }
  $('cal-prev').addEventListener('click', () => { st.vista.setMonth(st.vista.getMonth() - 1, 1); drawCal(); });
  $('cal-next').addEventListener('click', () => { st.vista.setMonth(st.vista.getMonth() + 1, 1); drawCal(); });

  /* ---- Horas ---- */
  const okH = (h) => (st.horas.find((x) => x.h === h) || {}).estado === 'ok';
  function pickHour(h) {
    if (st.a === null) { st.a = st.b = h; }
    else if (st.a === st.b && h === st.a) { st.a = st.b = null; }
    else if (st.a === st.b) {
      const lo = Math.min(st.a, h), hi = Math.max(st.a, h);
      let libre = true; for (let x = lo; x <= hi; x++) if (!okH(x)) libre = false;
      if (libre) { st.a = lo; st.b = hi; } else { st.a = st.b = h; }
    } else { st.a = st.b = h; }
    refresh();
  }
  function drawHours() {
    const box = $('hours'); box.innerHTML = '';
    st.horas.forEach((h) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'chip'; b.textContent = h.texto;
      b.dataset.estado = h.estado; b.disabled = h.estado !== 'ok';
      if (h.estado === 'mia') b.title = 'Ya tienes una reserva en esta hora';
      if (h.estado === 'pasada') b.title = 'Esta hora ya pasó';
      b.setAttribute('aria-pressed', st.a !== null && h.h >= st.a && h.h <= st.b ? 'true' : 'false');
      b.addEventListener('click', () => pickHour(h.h));
      box.appendChild(b);
    });
    const note = $('range-note').querySelector('span');
    if (st.a === null) note.textContent = 'Elige la hora de entrada.';
    else { const n = st.b - st.a + 1; note.textContent = `${fmtH(st.a)} – ${fmtH(st.b + 1)} · ${n} ${n === 1 ? 'hora' : 'horas'}`; }
  }

  /* ---- Mapa ---- */
  function msg(text, tipo) {
    const m = $('map-msg'); m.hidden = !text; m.querySelector('span').textContent = text || '';
    m.className = 'alert mapmsg alert--' + (tipo || 'info');
  }
  const esSala = (g) => !!g.querySelector('.seat');
  const apartados = (g, n) => (g.dataset.orden || '').split(',').map(Number).slice(0, n || 0);
  function clearSel() { st.esp = null; st.equipo = null; }
  function drawMap() {
    sps.forEach((g) => {
      const n = Number(g.dataset.num);
      const e = st.estados ? (st.estados[n] || 'nd') : 'nd';
      g.dataset.estado = e;
      g.dataset.sel = (st.esp === n && e === 'libre') ? 'true' : 'false';
      const txt = { libre: 'disponible', ocupado: 'apartado', nd: 'elige fecha y horario' }[e];
      g.setAttribute('aria-pressed', g.dataset.sel);
      g.setAttribute('aria-label', `${g.dataset.nombre}${esSala(g) ? ' (solo para equipos de trabajo)' : ''}, ${txt}`);
      g.setAttribute('aria-disabled', e === 'libre' ? 'false' : 'true');
      g.setAttribute('tabindex', e === 'libre' ? '0' : '-1');
      if (esSala(g)) {   // los asientos son solo ilustrativos: al elegir sala se resaltan los que se apartan para el equipo
        const sel = new Set(st.esp === n && st.equipo ? apartados(g, st.equipo) : []);
        g.querySelectorAll('.seat').forEach((s) => {
          s.dataset.estado = e === 'ocupado' ? 'ocupado' : 'libre';
          s.dataset.sel = sel.has(Number(s.dataset.asiento)) && e === 'libre' ? 'true' : 'false';
        });
      }
    });
    drawZones();
  }
  function drawZones() {
    const cnt = { salas: 0, fijo: 0, hot: 0 }, tot = { salas: 0, fijo: 0, hot: 0 };
    sps.forEach((g) => {
      const n = Number(g.dataset.num), z = esSala(g) ? 'salas' : (n <= 9 ? 'fijo' : 'hot');
      tot[z]++; if (st.estados && g.dataset.estado === 'libre') cnt[z]++;
    });
    document.querySelectorAll('.zone-chip[data-zone]').forEach((c) => {
      const z = c.dataset.zone, b = c.querySelector('b'), v = st.estados ? `${cnt[z]}/${tot[z]}` : '–';
      if (b.textContent !== v) { b.textContent = v; c.classList.remove('bump'); void c.offsetWidth; c.classList.add('bump'); }
    });
  }

  /* ---- Salas de juntas: solo para equipos ---- */
  const dlg = $('sala-dialog');
  let salaPend = null, nEquipo = MIN;
  const paso = (id) => ['sd-q', 'sd-n', 'sd-no'].forEach((x) => { $(x).hidden = x !== id; });
  function pintarEquipo() {
    const g = salaPend, cap = Number(g.dataset.cap);
    nEquipo = Math.max(MIN, Math.min(cap, nEquipo));
    $('sd-num').value = nEquipo;
    $('sd-menos').disabled = nEquipo <= MIN; $('sd-mas').disabled = nEquipo >= cap;
    $('sd-info').textContent = `Se apartarán ${nEquipo} asientos de ${g.dataset.nombre} (capacidad: ${cap}).`;
    // vista previa de los asientos en el mapa
    const sel = new Set(apartados(g, nEquipo));
    g.querySelectorAll('.seat').forEach((s) => { s.dataset.sel = sel.has(Number(s.dataset.asiento)) ? 'true' : 'false'; });
  }
  function abrirSala(g) {
    salaPend = g; nEquipo = Math.min(Math.max(MIN, st.equipo || MIN), Number(g.dataset.cap));
    $('sd-title').textContent = g.dataset.nombre; $('sd-min').textContent = MIN;
    $('sd-cap').textContent = g.dataset.cap; paso('sd-q'); dlg.showModal();
  }
  $('sd-si').addEventListener('click', () => { paso('sd-n'); pintarEquipo(); $('sd-num').focus(); });
  $('sd-no-btn').addEventListener('click', () => paso('sd-no'));
  $('sd-menos').addEventListener('click', () => { nEquipo--; pintarEquipo(); });
  $('sd-mas').addEventListener('click', () => { nEquipo++; pintarEquipo(); });
  $('sd-num').addEventListener('input', () => { const v = parseInt($('sd-num').value, 10); if (!isNaN(v)) { nEquipo = v; pintarEquipo(); } });
  $('sd-ok').addEventListener('click', () => {
    const n = Number(salaPend.dataset.num); st.esp = n; st.equipo = nEquipo; dlg.close(); msg(''); drawMap(); drawSummary();
  });
  dlg.addEventListener('close', () => { salaPend = null; drawMap(); });

  function pickSpace(g) {
    const n = Number(g.dataset.num);
    if (g.dataset.estado !== 'libre') {
      msg(g.dataset.estado === 'nd' ? 'Primero elige fecha y horario.' : `${g.dataset.nombre} ya está apartado en ese horario (incluye ${D.montaje} min de montaje antes y ${D.desmontaje} min de desmontaje después). Prueba con otro espacio u horario.`, g.dataset.estado === 'nd' ? 'info' : 'error');
      return;
    }
    msg('');
    if (esSala(g)) { abrirSala(g); return; }
    if (st.esp === n) clearSel(); else { st.esp = n; st.equipo = null; }
    drawMap(); drawSummary();
  }
  sps.forEach((g) => {
    g.addEventListener('click', () => pickSpace(g));
    g.addEventListener('keydown', (e) => { if (e.key !== 'Enter' && e.key !== ' ') return; e.preventDefault(); pickSpace(g); });
  });

  /* ---- Tooltip ---- */
  const tip = $('map-tip');
  plano.addEventListener('mousemove', (e) => {
    const g = e.target.closest('.sp'); if (!g) { tip.classList.remove('on'); return; }
    const est = { libre: 'Disponible', ocupado: 'Apartado', nd: 'Elige fecha y hora' }[g.dataset.estado] || '';
    const precio = st.precios[g.dataset.num] && g.dataset.estado === 'libre' ? ` · ${st.precios[g.dataset.num]}` : '';
    tip.innerHTML = `${g.dataset.nombre}<small>${est}${precio}${esSala(g) && g.dataset.estado === 'libre' ? ' · solo equipos' : ''}</small>`;
    tip.style.left = Math.min(e.clientX + 14, window.innerWidth - 220) + 'px'; tip.style.top = (e.clientY + 16) + 'px'; tip.classList.add('on');
  });
  plano.addEventListener('mouseleave', () => tip.classList.remove('on'));

  /* ---- Resumen, pasos y envío ---- */
  function nombreSel() {
    const g = spBy(st.esp); if (!g) return '';
    return g.dataset.nombre + (st.equipo ? ` · equipo de ${st.equipo}` : '');
  }
  function drawSummary() {
    const lista = !!(st.estados && st.esp && st.estados[st.esp] === 'libre' && (!esSala(spBy(st.esp)) || st.equipo));
    const e = $('sum-espacio'), nuevo = lista ? nombreSel() : 'Toca uno en el mapa';
    if (e.textContent !== nuevo) { e.textContent = nuevo; e.classList.remove('flash'); void e.offsetWidth; e.classList.add('flash'); }
    e.classList.toggle('is-empty', !lista);
    $('sum-fecha').textContent = parse(st.fecha).toLocaleDateString('es-MX', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    const h = $('sum-horario'); h.textContent = st.ventana ? st.ventana.texto : 'Elige una hora'; h.classList.toggle('is-empty', !st.ventana);
    const ac = $('sum-acceso'); ac.textContent = st.ventana ? st.ventana.acceso : '—'; ac.classList.toggle('is-empty', !st.ventana);
    const pr = $('sum-total'), val = lista ? st.precios[st.esp] : null; pr.textContent = val ? val + ' MXN' : '—'; pr.classList.toggle('is-empty', !val);
    $('btn-confirm').disabled = !(lista && st.ventana);
    $('f-espacio').value = st.esp || ''; $('f-equipo').value = st.equipo ? '1' : ''; $('f-integrantes').value = st.equipo || '';
    $('f-fecha').value = st.fecha; $('f-modo').value = st.modo;
    $('f-inicio').value = st.ventana ? st.ventana.inicio : ''; $('f-fin').value = st.ventana ? st.ventana.fin : '';
    const paso = !st.ventana ? 1 : (!lista ? 2 : 3);
    document.querySelectorAll('#stepper li').forEach((li) => {
      const n = Number(li.dataset.s); li.classList.toggle('done', n < paso); li.classList.toggle('now', n === paso);
    });
  }

  /* ---- Datos del servidor (con actualización en vivo) ---- */
  async function refresh(silent) {
    if (ctl) ctl.abort(); ctl = new AbortController();
    const p = new URLSearchParams({ fecha: st.fecha, modo: st.modo });
    if (st.modo === 'hora' && st.a !== null) { p.set('inicio', st.a); p.set('fin', st.b + 1); }
    if (!silent) $('map-frame').classList.add('is-loading');
    try {
      const r = await fetch(`${D.url}?${p}`, { signal: ctl.signal, headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (r.status === 401 || r.redirected) { location.reload(); return; }
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      st.horas = data.horas || [];
      if (st.modo === 'hora' && st.a === null && !silent) {
        const h = st.horas.find((x) => x.estado === 'ok');
        if (h) { st.a = st.b = h.h; return refresh(); }
      }
      const firma = JSON.stringify(data.estados);
      const cambio = st.firma !== null && st.firma !== firma && silent;
      st.firma = firma;
      st.estados = data.estados; st.precios = data.precios || {}; st.ventana = data.estados ? data.ventana : null;
      let perdido = false;
      if (st.esp) {
        const libre = st.estados && st.estados[st.esp] === 'libre';
        if (!libre) { perdido = true; const nom = nombreSel(); clearSel(); if (st.estados) msg(`${nom} acaba de ser apartado por otra persona. Elige otro lugar.`, 'error'); }
      }
      if (!perdido) { if (!data.estados) msg(data.mensaje || '', 'info'); else if (cambio) { msg('El mapa se actualizó: alguien acaba de apartar un lugar.', 'info'); setTimeout(() => { if ($('map-msg').textContent.startsWith('El mapa se')) msg(''); }, 4000); } else if (!silent) msg(''); }
      if (dlg.open && st.estados && salaPend && st.estados[Number(salaPend.dataset.num)] !== 'libre') dlg.close();
      drawHours(); drawMap(); drawSummary();
      $('map-frame').classList.remove('is-loading');
    } catch (err) {
      if (err.name === 'AbortError') return;
      $('map-frame').classList.remove('is-loading');
      if (!silent) msg('No pudimos actualizar la disponibilidad. Revisa tu conexión e inténtalo de nuevo.', 'error');
    }
  }
  setInterval(() => { if (!document.hidden && st.estados) refresh(true); }, 4000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(true); });

  form.querySelectorAll('input[name="modo_ui"]').forEach((r) => r.addEventListener('change', () => {
    st.modo = r.value; st.a = st.b = null; clearSel();
    $('hours-wrap').hidden = st.modo === 'dia'; $('day-note').hidden = st.modo !== 'dia';
    refresh();
  }));
  form.addEventListener('submit', (e) => { if ($('btn-confirm').disabled) e.preventDefault(); });

  drawCal(); drawMap(); drawSummary(); refresh();
})();
