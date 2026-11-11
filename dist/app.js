/* Space Apps Mentor — SPA vanilla (es-ES). Todo el contenido de usuario se inserta como texto. */
(() => {
  'use strict';

  // ---------- Constantes ----------
  const PITCH_AT = Date.parse('2026-11-15T15:00:00Z');
  const WARN_MIN = 90;
  const DANGER_MIN = 180;
  const REFRESH_MS = 20000;   // con varios mentores, refresco más frecuente
  const PHASE_VAR = { idea: '--ph-idea', problema: '--ph-problema', mvp: '--ph-mvp', demo: '--ph-demo', pitch: '--ph-pitch', entregado: '--ph-entregado' };
  const ROLE_COLOR = { dev: '#00f0ff', diseno: '#d3a8ff', negocio: '#ffb37a', ciencia: '#6ee7b7', otro: '#94a3b8' };

  const fmtTime = new Intl.DateTimeFormat('es-ES', { hour: '2-digit', minute: '2-digit' });
  const fmtDayTime = new Intl.DateTimeFormat('es-ES', { weekday: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const fmtFull = new Intl.DateTimeFormat('es-ES', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
  const collator = new Intl.Collator('es-ES', { sensitivity: 'base', numeric: true });

  // ---------- Estado ----------
  let S = null;                 // /api/state
  let route = { name: 'tablero', id: null };
  let currentTeam = null;       // detalle en ficha
  let dragging = false;
  let ME = { auth_required: false, logged_in: true, name: '' };   // /api/me
  const prefs = loadPrefs();

  // ---------- Utilidades DOM ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'draggable', 'hidden', 'tabIndex', 'rows', 'multiple']);

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'dataset') Object.assign(el.dataset, v);
        else if (k === 'style') el.style.cssText = v;
        else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (PROPS.has(k)) el[k] = v;
        else el.setAttribute(k, v === true ? '' : String(v));
      }
    }
    append(el, kids);
    return el;
  }
  function append(el, kids) {
    for (const k of kids.flat(Infinity)) {
      if (k == null || k === false) continue;
      el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return el;
  }
  // SVG estático de confianza (nunca contenido de usuario)
  const ICONS = {
    users: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5M16 4.8a3.5 3.5 0 0 1 0 6.4M18 14.8c2 .7 3.2 2.4 3.5 5.2"/></svg>',
  };
  function icon(name) { const s = document.createElement('span'); s.className = 'ico'; s.innerHTML = ICONS[name]; return s.firstChild; }

  function highlight(text, q) {
    text = text || '';
    const frag = document.createDocumentFragment();
    if (!q) { frag.append(text); return frag; }
    const lt = text.toLowerCase(), lq = q.toLowerCase();
    let i = 0, j;
    while ((j = lt.indexOf(lq, i)) !== -1) {
      if (j > i) frag.append(text.slice(i, j));
      frag.append(h('mark', null, text.slice(j, j + q.length)));
      i = j + q.length;
    }
    frag.append(text.slice(i));
    return frag;
  }
  function snippet(text, q, len = 90) {
    text = (text || '').replace(/\s+/g, ' ');
    const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
    if (i < 0 || text.length <= len) return text.length > len ? text.slice(0, len) + '…' : text;
    const start = Math.max(0, i - 30);
    return (start > 0 ? '…' : '') + text.slice(start, start + len) + (start + len < text.length ? '…' : '');
  }

  // ---------- Preferencias locales (solo comodidad) ----------
  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem('sam-prefs') || '{}') || {}; } catch (e) { return {}; }
  }
  function savePrefs() { try { localStorage.setItem('sam-prefs', JSON.stringify(prefs)); } catch (e) { /* sin almacenamiento */ } }

  // ---------- Notas privadas (solo en este navegador) ----------
  // Las notas de sesión y las notas sobre miembros NO se envían al servidor.
  const PN_KEY = 'sam-private-notes-v1';
  let pnOk = true;
  const PN = loadPN();
  function loadPN() {
    try {
      const d = JSON.parse(localStorage.getItem(PN_KEY) || '{}') || {};
      return { teams: d.teams || {}, members: d.members || {} };
    } catch (e) { pnOk = false; return { teams: {}, members: {} }; }
  }
  function savePN() {
    try { localStorage.setItem(PN_KEY, JSON.stringify(PN)); pnOk = true; return true; }
    catch (e) { pnOk = false; toast('Este navegador no permite guardar notas locales (¿modo privado?). Se perderán al recargar.', true); return false; }
  }
  const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  function teamNotes(teamId) {
    return [...(PN.teams[teamId] || [])].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
  }
  function lastNote(teamId) { return teamNotes(teamId)[0] || null; }
  function addNote(teamId, data) {
    const n = Object.assign({ id: newId(), created_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z') }, data);
    (PN.teams[teamId] = PN.teams[teamId] || []).push(n);
    savePN();
    return n;
  }
  function updateNote(teamId, noteId, data) {
    const n = (PN.teams[teamId] || []).find((x) => x.id === noteId);
    if (n) { Object.assign(n, data); savePN(); }
    return n;
  }
  function deleteNote(teamId, noteId) {
    PN.teams[teamId] = (PN.teams[teamId] || []).filter((x) => x.id !== noteId);
    if (!PN.teams[teamId].length) delete PN.teams[teamId];
    savePN();
  }
  function forgetTeam(team) {
    delete PN.teams[team.id];
    for (const m of team.members || []) delete PN.members[m.id];
    savePN();
  }
  const memberNote = (memberId) => PN.members[memberId] || '';
  function setMemberNote(memberId, text) {
    if (text) PN.members[memberId] = text; else delete PN.members[memberId];
    return savePN();
  }
  function exportPN() {
    const names = Object.fromEntries((S && S.teams || []).map((t) => [t.id, t.name]));
    const blob = new Blob([JSON.stringify({ kind: 'sam-private-notes', version: 1, exported_at: new Date().toISOString(), mentor: ME.name || '', team_names: names, teams: PN.teams, members: PN.members }, null, 2)], { type: 'application/json' });
    const a = h('a', { href: URL.createObjectURL(blob), download: `mis-notas-spaceapps-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '')}.json` });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  function importPN(data) {
    if (!data || data.kind !== 'sam-private-notes' || typeof data.teams !== 'object') throw new Error('El fichero no es una copia de tus notas privadas.');
    let added = 0;
    for (const [tid, list] of Object.entries(data.teams || {})) {
      if (!Array.isArray(list)) continue;
      const cur = PN.teams[tid] = PN.teams[tid] || [];
      for (const n of list) if (n && n.id && !cur.some((x) => x.id === n.id)) { cur.push(n); added++; }
    }
    for (const [mid, txt] of Object.entries(data.members || {})) if (typeof txt === 'string' && !PN.members[mid]) PN.members[mid] = txt;
    savePN();
    return added;
  }

  // ---------- API ----------
  async function api(method, url, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    let res;
    try { res = await fetch(url, opt); }
    catch (e) { throw new Error('No hay conexión con el servidor. Revisa tu conexión y reintenta.'); }
    let data = null;
    const txt = await res.text();
    if (txt) { try { data = JSON.parse(txt); } catch (e) { data = null; } }
    if (res.status === 401 && data && data.login) { ME.logged_in = false; showLogin(); }
    if (!res.ok) throw new Error((data && data.error) || `Error ${res.status}`);
    return data;
  }
  async function guard(promise, okMsg) {
    try { const r = await promise; if (okMsg) toast(okMsg); return r; }
    catch (e) { toast(e.message, true); throw e; }
  }
  async function loadState() { S = await api('GET', '/api/state'); return S; }

  // ---------- Helpers de dominio ----------
  const phaseLabel = (k) => (S.phases.find((p) => p.key === k) || { label: k }).label;
  const roleLabel = (k) => ((S.roles || []).find((p) => p.key === k) || { label: k || '—' }).label;
  const kindLabel = (k) => ((S.note_kinds || []).find((p) => p.key === k) || { label: k }).label;
  const phVar = (k) => `--ph: var(${PHASE_VAR[k] || '--primary-cyan'})`;
  const challengeById = (id) => (S.challenges || []).find((c) => c.id === id) || null;
  const ts = (iso) => (iso ? Date.parse(iso) : NaN);

  function minsSince(iso) { const t = ts(iso); return isNaN(t) ? null : Math.max(0, Math.floor((Date.now() - t) / 60000)); }
  function relTime(iso) {
    const m = minsSince(iso);
    if (m == null) return 'nunca';
    if (m < 1) return 'ahora mismo';
    if (m < 60) return `hace ${m} min`;
    const hh = Math.floor(m / 60), mm = m % 60;
    if (hh < 6) return mm ? `hace ${hh} h ${mm} min` : `hace ${hh} h`;
    if (hh < 48) return `hace ${hh} h`;
    return `hace ${Math.floor(hh / 24)} d`;
  }
  function visitClass(iso) {
    const m = minsSince(iso);
    if (m == null || m > DANGER_MIN) return 'danger';
    if (m > WARN_MIN) return 'warn';
    return '';
  }
  function visitTag(iso, prefix = '') {
    const cls = visitClass(iso);
    return h('span', {
      class: 'time-tag ' + cls, dataset: { visit: iso || '', prefix },
      title: iso ? 'Última visita: ' + fmtFull.format(new Date(iso)) : 'Aún no visitado',
    }, prefix + (iso ? relTime(iso) : 'sin visita'));
  }
  function refreshRelTimes() {
    for (const el of $$('[data-visit]')) {
      const iso = el.dataset.visit || null;
      el.textContent = (el.dataset.prefix || '') + (iso ? relTime(iso) : 'sin visita');
      el.className = 'time-tag ' + visitClass(iso);
    }
    for (const el of $$('[data-rel]')) el.textContent = relTime(el.dataset.rel);
  }
  function chShort(t) {
    if (!t.challenge_id) return null;
    return { num: t.challenge_num, title: t.challenge_title || (challengeById(t.challenge_id) || {}).title || '' };
  }
  function sortForBoard(a, b) {
    if (!!b.attention - !!a.attention) return (!!b.attention) - (!!a.attention);
    const ta = ts(a.last_visit_at), tb = ts(b.last_visit_at);
    const va = isNaN(ta) ? -Infinity : ta, vb = isNaN(tb) ? -Infinity : tb;
    if (va !== vb) return va - vb;
    return collator.compare(a.name, b.name);
  }
  function challengeOptions(selected, emptyLabel = '— Sin reto asignado —') {
    const opts = [h('option', { value: '' }, emptyLabel)];
    const list = [...(S.challenges || [])].sort((a, b) => (a.num || 0) - (b.num || 0));
    for (const c of list) opts.push(h('option', { value: String(c.id), selected: c.id === selected }, `${c.num != null ? c.num + '. ' : ''}${c.title}`));
    return opts;
  }
  function roleOptions(selected) {
    return (S.roles || []).map((r) => h('option', { value: r.key, selected: r.key === (selected || 'otro') }, r.label));
  }
  function autoGrow(ta) {
    const fit = () => { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight + 2, 420) + 'px'; };
    ta.addEventListener('input', fit);
    requestAnimationFrame(fit);
    return ta;
  }
  function flash(el, cls = 'saved') { el.classList.add(cls); setTimeout(() => el.classList.remove(cls), 900); }

  // ---------- Toasts ----------
  function toast(msg, isErr = false) {
    const t = h('div', { class: 'toast' + (isErr ? ' err' : ''), role: isErr ? 'alert' : 'status' }, msg);
    const box = $('#toasts');
    box.appendChild(t);
    while (box.children.length > 4) box.firstElementChild.remove();
    setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 320); }, isErr ? 5000 : 2200);
  }

  // ---------- Router ----------
  function parseHash() {
    const p = (location.hash.replace(/^#\/?/, '') || '').split('/').filter(Boolean);
    if (!p.length) return { name: 'tablero' };
    if (p[0] === 'equipos') return p[1] ? { name: 'ficha', id: +p[1] } : { name: 'equipos' };
    if (p[0] === 'retos') return p[1] ? { name: 'reto', id: +p[1] } : { name: 'retos' };
    if (p[0] === 'metodologias') return { name: 'metodologias' };
    return { name: 'tablero' };
  }
  async function render(opts = {}) {
    route = parseHash();
    const navKey = { tablero: 'tablero', equipos: 'equipos', ficha: 'equipos', retos: 'retos', reto: 'retos', metodologias: 'metodologias' }[route.name];
    for (const a of $$('[data-nav]')) a.classList.toggle('active', a.dataset.nav === navKey);
    const app = $('#app');
    const keepScroll = opts.keepScroll ? window.scrollY : 0;
    try {
      if (!S || opts.reload !== false) await loadState();
      let view;
      if (route.name === 'tablero') view = viewBoard();
      else if (route.name === 'equipos') view = viewTeams();
      else if (route.name === 'ficha') view = await viewTeam(route.id);
      else if (route.name === 'retos') view = viewChallenges();
      else if (route.name === 'reto') view = await viewChallenge(route.id);
      else view = viewMethods();
      app.replaceChildren(view);
      document.title = titleFor() + ' · Space Apps Mentor';
    } catch (e) {
      app.replaceChildren(h('div', { class: 'glass-card empty' },
        h('div', { class: 'orb' }), h('div', { class: 'big' }, 'No se pudo cargar'),
        h('p', null, e.message), h('button', { class: 'btn-space-outline btn-sm', onclick: () => render() }, 'Reintentar')));
    }
    window.scrollTo(0, keepScroll);
  }
  function titleFor() {
    return { tablero: 'Tablero', equipos: 'Equipos', ficha: currentTeam ? currentTeam.name : 'Equipo', retos: 'Retos', reto: 'Reto', metodologias: 'Metodologías' }[route.name];
  }
  const go = (hash) => { if (location.hash === hash) render(); else location.hash = hash; };

  // ---------- Vista: Tablero ----------
  function viewBoard() {
    const teams = S.teams || [];
    const filterCh = prefs.boardCh || '';
    const onlyAttn = !!prefs.onlyAttn;
    const shown = teams.filter((t) => (!filterCh || String(t.challenge_id || '') === filterCh || (filterCh === 'none' && !t.challenge_id)) && (!onlyAttn || t.attention));
    const overdue = teams.filter((t) => visitClass(t.last_visit_at)).length;
    const attn = teams.filter((t) => t.attention).length;

    const head = h('div', { class: 'page-head' },
      h('div', { class: 'grow' }, h('div', { class: 'section-tag' }, 'Control de misión'), h('h2', { class: 'section-title' }, 'Tablero de equipos')),
      h('div', { class: 'board-stats' },
        h('div', { class: 'stat' }, h('b', null, teams.length), h('span', null, 'equipos')),
        h('div', { class: 'stat warn', title: `Sin visita en más de ${WARN_MIN} min o nunca visitados` }, h('b', null, overdue), h('span', null, `sin visita > ${WARN_MIN} min`)),
        h('div', { class: 'stat star' }, h('b', null, attn), h('span', null, 'con atención'))));

    if (!teams.length) {
      return h('div', null, head, emptyState('Aún no hay equipos', 'Pulsa n o el botón para dar de alta el primero. Tardas menos de un minuto.', true));
    }

    const sel = h('select', { class: 'fc', 'aria-label': 'Filtrar por reto', onchange: (e) => { prefs.boardCh = e.target.value; savePrefs(); render({ reload: false }); } },
      h('option', { value: '' }, 'Todos los retos'),
      h('option', { value: 'none', selected: filterCh === 'none' }, 'Sin reto asignado'),
      [...S.challenges].sort((a, b) => a.num - b.num).map((c) => h('option', { value: String(c.id), selected: String(c.id) === filterCh }, `${c.num}. ${c.title} (${c.team_count || 0})`)));
    const tog = h('label', { class: 'toggle' },
      h('input', { type: 'checkbox', checked: onlyAttn, onchange: (e) => { prefs.onlyAttn = e.target.checked; savePrefs(); render({ reload: false }); } }), '★ Solo con atención');
    const toolbar = h('div', { class: 'toolbar' }, sel, tog,
      h('span', { class: 'dim', style: 'font-size:13px;margin-left:auto' }, 'Arrastra una tarjeta para cambiar de fase · orden: atención y visita más antigua primero'));

    const board = h('div', { class: 'board' });
    for (const p of S.phases) {
      const list = shown.filter((t) => t.phase === p.key).sort(sortForBoard);
      const col = h('section', { class: 'col', style: phVar(p.key), dataset: { phase: p.key }, 'aria-label': p.label },
        h('div', { class: 'col-head' }, h('span', { class: 'dot' }), h('span', { class: 'col-title' }, p.label), h('span', { class: 'col-count' }, list.length)),
        list.length ? list.map(teamCard) : h('div', { class: 'col-empty' }, 'Suelta aquí'));
      col.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; col.classList.add('drop'); });
      col.addEventListener('dragleave', (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove('drop'); });
      col.addEventListener('drop', (e) => {
        e.preventDefault(); col.classList.remove('drop');
        const id = +e.dataTransfer.getData('text/plain');
        const t = S.teams.find((x) => x.id === id);
        if (!t || t.phase === p.key) return;
        const prev = t.phase;
        t.phase = p.key;
        render({ reload: false, keepScroll: true });
        api('PATCH', `/api/teams/${id}`, { phase: p.key })
          .then(() => toast(`${t.name} → ${p.label}`))
          .catch((err) => { t.phase = prev; toast(err.message, true); render({ reload: false, keepScroll: true }); });
      });
      board.appendChild(col);
    }
    return h('div', null, head, toolbar, board);
  }

  function teamCard(t) {
    const ch = chShort(t);
    const card = h('article', {
      class: 'glass-card tcard' + (t.attention ? ' attn' : ''), style: phVar(t.phase), draggable: true, tabIndex: 0,
      'aria-label': `Equipo ${t.name}`, onclick: () => go(`#/equipos/${t.id}`),
      onkeydown: (e) => { if (e.key === 'Enter') go(`#/equipos/${t.id}`); },
    },
      h('div', { class: 'tcard-top' },
        h('div', { class: 'tcard-name' }, t.name),
        t.table_label ? h('span', { class: 'table-tag', title: 'Mesa' }, t.table_label) : null,
        starBtn(t)),
      h('div', { class: 'tcard-ch', title: ch ? `${ch.num}. ${ch.title}` : 'Sin reto' },
        ch ? h('span', { class: 'num-badge' }, ch.num ?? '?') : h('span', { class: 'num-badge none' }, '—'),
        h('span', null, ch ? ch.title : 'Sin reto asignado')),
      h('div', { class: 'tcard-meta' },
        h('span', { class: 'mem', title: 'Miembros' }, icon('users'), t.member_count || 0),
        visitTag(t.last_visit_at)),
      (() => { const n = lastNote(t.id); const txt = n && (n.body || n.next_steps); return txt ? h('div', { class: 'tcard-note', title: 'Tu última nota privada: ' + txt }, txt) : null; })());
    card.addEventListener('dragstart', (e) => {
      dragging = true; e.dataTransfer.setData('text/plain', String(t.id)); e.dataTransfer.effectAllowed = 'move';
      requestAnimationFrame(() => card.classList.add('dragging'));
    });
    card.addEventListener('dragend', () => { dragging = false; card.classList.remove('dragging'); $$('.col.drop').forEach((c) => c.classList.remove('drop')); });
    return card;
  }

  function starBtn(t, onDone) {
    return h('button', {
      class: 'star-btn' + (t.attention ? ' on' : ''), type: 'button',
      title: t.attention ? 'Quitar marca de atención' : 'Marcar: necesita atención', 'aria-pressed': t.attention ? 'true' : 'false',
      onclick: async (e) => {
        e.stopPropagation();
        const val = t.attention ? 0 : 1;
        try {
          await api('PATCH', `/api/teams/${t.id}`, { attention: val });
          t.attention = val;
          toast(val ? `★ ${t.name} necesita atención` : `${t.name}: atención retirada`);
          if (onDone) onDone(); else render({ reload: false, keepScroll: true });
        } catch (err) { toast(err.message, true); }
      },
    }, t.attention ? '★' : '☆');
  }

  function emptyState(title, text, withBtn) {
    return h('div', { class: 'glass-card empty' }, h('div', { class: 'orb' }), h('div', { class: 'big' }, title), h('p', null, text),
      withBtn ? h('button', { class: 'btn-space-primary', onclick: () => openNewTeam() }, '+ Nuevo equipo') : null);
  }

  // ---------- Vista: Equipos (tabla) ----------
  function viewTeams() {
    const teams = [...(S.teams || [])];
    const head = h('div', { class: 'page-head' },
      h('div', { class: 'grow' }, h('div', { class: 'section-tag' }, `${teams.length} equipos`), h('h2', { class: 'section-title' }, 'Equipos')),
      h('button', { class: 'btn-space-primary btn-sm', onclick: () => openNewTeam() }, '+ Equipo'));
    if (!teams.length) return h('div', null, head, emptyState('Aún no hay equipos', 'Pulsa n para crear el primero.', true));

    const phaseIdx = Object.fromEntries(S.phases.map((p, i) => [p.key, i]));
    const cols = [
      { k: 'attention', label: '★', get: (t) => (t.attention ? 1 : 0) },
      { k: 'name', label: 'Equipo', get: (t) => t.name },
      { k: 'table_label', label: 'Mesa', get: (t) => t.table_label || '' },
      { k: 'challenge', label: 'Reto', get: (t) => (t.challenge_id ? t.challenge_num : 999) },
      { k: 'phase', label: 'Fase', get: (t) => phaseIdx[t.phase] ?? 99 },
      { k: 'member_count', label: 'Miembros', get: (t) => t.member_count || 0 },
      { k: 'last_visit_at', label: 'Última visita', get: (t) => (t.last_visit_at ? ts(t.last_visit_at) : -1) },
    ];
    const sk = prefs.sortKey || 'name', dir = prefs.sortDir || 1;
    const col = cols.find((c) => c.k === sk) || cols[1];
    teams.sort((a, b) => {
      const va = col.get(a), vb = col.get(b);
      const r = typeof va === 'string' ? collator.compare(va, vb) : va - vb;
      return (r || collator.compare(a.name, b.name)) * (r ? dir : 1);
    });
    const thead = h('thead', null, h('tr', null, cols.map((c) => h('th', {
      class: c.k === sk ? 'sorted' : '', scope: 'col', tabIndex: 0, 'aria-sort': c.k === sk ? (dir > 0 ? 'ascending' : 'descending') : 'none',
      onclick: () => sortBy(c.k), onkeydown: (e) => { if (e.key === 'Enter') sortBy(c.k); },
    }, c.label, c.k === sk ? h('span', { class: 'arr' }, dir > 0 ? '▲' : '▼') : null))));
    function sortBy(k) { if (prefs.sortKey === k) prefs.sortDir = -(prefs.sortDir || 1); else { prefs.sortKey = k; prefs.sortDir = 1; } savePrefs(); render({ reload: false }); }

    const tbody = h('tbody', null, teams.map((t) => {
      const ch = chShort(t);
      return h('tr', { onclick: () => go(`#/equipos/${t.id}`) },
        h('td', { style: 'width:40px' }, starBtn(t)),
        h('td', null, h('div', { class: 'name' }, t.name), t.idea ? h('div', { class: 'idea' }, t.idea) : null),
        h('td', null, t.table_label ? h('span', { class: 'table-tag' }, t.table_label) : h('span', { class: 'dim' }, '—')),
        h('td', null, ch ? h('div', { class: 'row', style: 'gap:8px' }, h('span', { class: 'num-badge' }, ch.num), h('span', { class: 'muted', style: 'font-size:14px' }, ch.title)) : h('span', { class: 'dim' }, 'Sin reto')),
        h('td', null, h('span', { class: 'phase-chip', style: phVar(t.phase) }, phaseLabel(t.phase))),
        h('td', { style: 'text-align:center' }, t.member_count || 0),
        h('td', null, visitTag(t.last_visit_at)));
    }));
    return h('div', null, head, h('div', { class: 'glass-card tbl-wrap' }, h('table', { class: 'tbl' }, thead, tbody)));
  }

  // ---------- Vista: Ficha de equipo ----------
  async function viewTeam(id) {
    const t = await api('GET', `/api/teams/${id}`);
    currentTeam = t;
    const wrap = h('div', { class: 'ficha', dataset: { team: String(t.id) } });
    wrap.append(
      h('a', { class: 'back', href: '#/' }, '← Tablero'),
      teamHeader(t),
      h('div', { class: 'team-grid' },
        h('div', { class: 'stack' }, projectPanel(t), membersPanel(t), challengePanel(t)),
        h('div', { class: 'stack' }, notesPanel(t))));
    return wrap;
  }

  async function patchTeam(field, value, el) {
    const t = currentTeam;
    if (!t) return;
    try {
      const upd = await api('PATCH', `/api/teams/${t.id}`, { [field]: value });
      Object.assign(t, upd || { [field]: value });
      if (el) flash(el);
      toast('Guardado');
      return upd;
    } catch (e) { if (el) flash(el, 'err'); toast(e.message, true); throw e; }
  }
  // Campo con autoguardado al perder el foco
  function autoField(tag, field, attrs = {}) {
    const t = currentTeam;
    const el = h(tag, Object.assign({ class: 'fc', dataset: { field } }, attrs));
    el.value = t[field] || '';
    el.dataset.orig = el.value;
    el.addEventListener('blur', async () => {
      if (el.value === el.dataset.orig) return;
      const v = el.value;
      if (field === 'name' && !v.trim()) { el.value = el.dataset.orig; toast('El nombre no puede quedar vacío', true); return; }
      try { await patchTeam(field, v, el); el.dataset.orig = v; if (field === 'links') renderLinks(); if (field === 'name') document.title = v + ' · Space Apps Mentor'; } catch (e) { /* toast ya mostrado */ }
    });
    if (tag === 'input') el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } });
    if (tag === 'textarea') autoGrow(el);
    return el;
  }
  let renderLinks = () => {};

  function teamHeader(t) {
    const phaseIdx = S.phases.findIndex((p) => p.key === t.phase);
    const pills = h('div', { class: 'phase-pills', role: 'radiogroup', 'aria-label': 'Fase' }, S.phases.map((p, i) => h('button', {
      type: 'button', role: 'radio', 'aria-checked': p.key === t.phase ? 'true' : 'false', style: phVar(p.key),
      class: 'phase-pill' + (p.key === t.phase ? ' active' : i < phaseIdx ? ' done' : ''),
      onclick: async () => {
        if (p.key === currentTeam.phase) return;
        try { await patchTeam('phase', p.key); rerenderHeader(); } catch (e) { /* */ }
      },
    }, h('span', { class: 'n' }, i + 1), p.label)));

    const chSel = h('select', { class: 'fc', 'aria-label': 'Reto oficial' }, challengeOptions(t.challenge_id));
    chSel.addEventListener('change', async () => {
      const v = chSel.value ? +chSel.value : null;
      try { await patchTeam('challenge_id', v, chSel); currentTeam.challenge = challengeById(v); replacePanel('challenge', challengePanel(currentTeam)); } catch (e) { chSel.value = currentTeam.challenge_id ? String(currentTeam.challenge_id) : ''; }
    });

    const last = teamNotes(t.id).find((n) => n.next_steps && n.next_steps.trim());
    const card = h('section', { class: 'glass-card team-head', id: 'team-head' },
      h('div', { class: 'th-row' },
        starBtn(t, rerenderHeader),
        autoField('input', 'name', { class: 'th-name', 'aria-label': 'Nombre del equipo', maxlength: 120 }),
        h('label', { class: 'th-table', title: 'Mesa' }, autoField('input', 'table_label', { placeholder: 'Mesa', 'aria-label': 'Mesa' })),
        h('button', { class: 'btn-ghost danger btn-sm', type: 'button', onclick: deleteTeam }, 'Borrar')),
      h('div', { class: 'th-sub' }, pills),
      h('div', { class: 'th-sub' },
        chSel,
        h('div', { class: 'th-meta' },
          h('span', null, 'Última visita'), visitTag(t.last_visit_at),
          t.last_visit_by ? h('span', { class: 'dim' }, 'por ' + t.last_visit_by) : null,
          h('span', { class: 'dim' }, '· creado ' + fmtDayTime.format(new Date(t.created_at))),
          t.updated_by ? h('span', { class: 'dim', title: fmtFull.format(new Date(t.updated_at)) }, '· última edición: ' + t.updated_by) : null)),
      last ? h('div', { class: 'pending-box' },
        h('span', { class: 'lab' }, 'Tus siguientes pasos'),
        h('span', { class: 'txt' }, last.next_steps),
        h('span', { class: 'when', dataset: { rel: last.created_at } }, relTime(last.created_at))) : null);
    // el input de nombre usa clase propia (sin .fc)
    const nm = $('.th-name', card); nm.classList.remove('fc');
    return card;
  }
  function rerenderHeader() {
    const old = $('#team-head');
    if (old && currentTeam) old.replaceWith(teamHeader(currentTeam));
  }
  function replacePanel(key, node) { const old = $(`[data-panel="${key}"]`); if (old) old.replaceWith(node); }

  async function deleteTeam() {
    const t = currentTeam;
    if (!confirm(`¿Borrar el equipo «${t.name}» y sus miembros PARA TODOS LOS MENTORES? No se puede deshacer.`)) return;
    try { await api('DELETE', `/api/teams/${t.id}`); forgetTeam(t); toast(`Equipo «${t.name}» borrado`); currentTeam = null; go('#/'); }
    catch (e) { toast(e.message, true); }
  }

  function projectPanel(t) {
    const linksOut = h('div', { class: 'links-out' });
    renderLinks = () => {
      const urls = (currentTeam.links || '').match(/https?:\/\/[^\s<>"']+/g) || [];
      linksOut.replaceChildren(...urls.slice(0, 12).map((u) => h('a', { href: u, target: '_blank', rel: 'noopener noreferrer', title: u }, u.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '') + ' ↗')));
    };
    renderLinks();
    return h('section', { class: 'glass-card panel', dataset: { panel: 'project' } },
      h('div', { class: 'panel-head' }, h('span', { class: 'panel-title' }, 'Proyecto'), h('span', { class: 'right dim', style: 'font-size:13px' }, 'Se guarda al salir del campo')),
      h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Idea en una frase'), autoField('input', 'idea', { placeholder: 'Ej.: App que alerta a agricultores de heladas con datos de satélite' })),
      h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Problema', h('span', { class: 'hint' }, '¿para quién?, ¿cómo lo sabemos?')), autoField('textarea', 'problem', { rows: 2, placeholder: 'Quién sufre el problema, evidencia, tamaño…' })),
      h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Solución', h('span', { class: 'hint' }, 'MVP y datos NASA que usa')), autoField('textarea', 'solution', { rows: 2, placeholder: 'Qué construyen en 48 h, qué datos/recursos usan…' })),
      h('div', { class: 'field', style: 'margin-bottom:0' }, h('label', { class: 'lbl' }, 'Enlaces', h('span', { class: 'hint' }, 'repo, demo, slides, Figma… uno por línea')), autoField('textarea', 'links', { rows: 1, placeholder: 'https://github.com/…' }), linksOut));
  }

  function membersPanel(t) {
    const list = h('div', { class: 'members' });
    const count = h('span', { class: 'count' }, (t.members || []).length);
    const draw = () => {
      count.textContent = currentTeam.members.length;
      list.replaceChildren(...(currentTeam.members.length ? currentTeam.members.map(memberRow) : [h('div', { class: 'dim', style: 'font-size:14px;padding:4px 2px' }, 'Sin miembros todavía. Añádelos abajo (Enter para guardar).')]));
    };
    function memberRow(m) {
      const save = async (field, el) => {
        const v = el.value;
        if (v === (m[field] || '')) return;
        if (field === 'name' && !v.trim()) { el.value = m.name; toast('El nombre no puede quedar vacío', true); return; }
        try { const r = await api('PATCH', `/api/members/${m.id}`, { [field]: v }); Object.assign(m, r || { [field]: v }); flash(el); toast('Miembro guardado'); }
        catch (e) { flash(el, 'err'); toast(e.message, true); }
      };
      const inp = (field, ph, extra = {}) => {
        const el = h('input', Object.assign({ class: 'fc', placeholder: ph, value: m[field] || '', 'aria-label': ph }, extra));
        el.addEventListener('blur', () => save(field, el));
        el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } });
        return el;
      };
      const role = h('select', { class: 'fc', 'aria-label': 'Rol', style: `color:${ROLE_COLOR[m.role] || '#fff'}` }, roleOptions(m.role));
      role.addEventListener('change', () => { role.style.color = ROLE_COLOR[role.value] || '#fff'; save('role', role); });
      return h('div', { class: 'mrow' },
        inp('name', 'Nombre', { style: 'font-weight:600' }), role, inp('skills', 'Skills (Python, Figma, pitch…)'),
        h('button', {
          class: 'link-btn danger del', type: 'button', title: 'Borrar miembro', 'aria-label': `Borrar ${m.name}`,
          onclick: async () => {
            if (!confirm(`¿Borrar a ${m.name} del equipo?`)) return;
            try { await api('DELETE', `/api/members/${m.id}`); currentTeam.members = currentTeam.members.filter((x) => x.id !== m.id); draw(); toast('Miembro borrado'); }
            catch (e) { toast(e.message, true); }
          },
        }, '✕'),
        h('div', { class: 'notes' }, privateMemberNote(m)));
    }
    function privateMemberNote(m) {
      const el = h('input', { class: 'fc', placeholder: '🔒 Nota privada (solo tú la ves)', value: memberNote(m.id), 'aria-label': 'Nota privada sobre ' + m.name, style: 'font-size:13.5px' });
      el.addEventListener('blur', () => { const v = el.value.trim(); if (v === memberNote(m.id)) return; if (setMemberNote(m.id, v)) { flash(el); toast('Nota privada guardada'); } });
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } });
      return el;
    }
    const nName = h('input', { class: 'fc', placeholder: 'Nuevo miembro', 'aria-label': 'Nombre del nuevo miembro' });
    const nRole = h('select', { class: 'fc', 'aria-label': 'Rol' }, roleOptions('otro'));
    const nSkills = h('input', { class: 'fc', placeholder: 'Skills', 'aria-label': 'Skills' });
    const add = async () => {
      const name = nName.value.trim();
      if (!name) { nName.focus(); toast('Escribe el nombre del miembro', true); return; }
      try {
        const m = await api('POST', `/api/teams/${currentTeam.id}/members`, { name, role: nRole.value, skills: nSkills.value.trim() });
        currentTeam.members.push(m); draw(); nName.value = ''; nSkills.value = ''; nRole.value = 'otro'; nName.focus(); toast(`${m.name} añadido`);
      } catch (e) { toast(e.message, true); }
    };
    for (const el of [nName, nSkills, nRole]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
    draw();
    return h('section', { class: 'glass-card panel', dataset: { panel: 'members' } },
      h('div', { class: 'panel-head' }, h('span', { class: 'panel-title' }, 'Miembros'), count),
      list,
      h('div', { class: 'madd' }, nName, nRole, nSkills, h('button', { class: 'btn-space-outline btn-xs', type: 'button', onclick: add }, '+ Añadir')));
  }

  function challengePanel(t) {
    const c = t.challenge || challengeById(t.challenge_id);
    if (!c) {
      return h('section', { class: 'glass-card panel ch-sum', dataset: { panel: 'challenge' } },
        h('div', { class: 'panel-head' }, h('span', { class: 'panel-title' }, 'Reto oficial')),
        h('p', { class: 'muted', style: 'margin:0' }, 'Sin reto asignado. Elige uno en el selector de la cabecera o '), h('a', { href: '#/retos' }, 'explora los retos →'));
    }
    return h('section', { class: 'glass-card panel ch-sum', dataset: { panel: 'challenge' } },
      h('div', { class: 'panel-head' }, h('span', { class: 'panel-title' }, 'Reto oficial'),
        h('span', { class: 'right' }, c.url ? h('a', { href: c.url, target: '_blank', rel: 'noopener noreferrer', style: 'font-size:13.5px;font-weight:600' }, 'Ver en NASA ↗') : null)),
      h('div', { class: 'row', style: 'gap:8px' }, h('span', { class: 'num-badge' }, c.num), c.category ? h('span', { class: 'ch-cat' }, c.category) : null),
      h('a', { href: `#/retos/${c.id}`, style: 'color:inherit' }, h('div', { class: 'ch-title' }, c.title)),
      c.title_en ? h('div', { class: 'ch-en' }, c.title_en) : null,
      c.summary ? h('p', null, c.summary) : null,
      difficultyChips(c.difficulty));
  }
  function difficultyChips(d) {
    if (!d) return null;
    const cls = (x) => (/avanz|advanced|experto/i.test(x) ? 'orange' : /princip|beginner|básic/i.test(x) ? 'cyan' : 'purple');
    return h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap' }, d.split(/\s*[·,|/]\s*/).filter(Boolean).map((x) => h('span', { class: 'chip ' + cls(x) }, x)));
  }

  function notesPanel(t) {
    const tl = h('div', { class: 'timeline' });
    const count = h('span', { class: 'count' }, teamNotes(t.id).length);
    let kind = 'mentoria';
    const kindPills = h('div', { class: 'kind-pills', role: 'radiogroup', 'aria-label': 'Tipo de nota' });
    const drawKinds = () => kindPills.replaceChildren(...(S.note_kinds || []).map((k) => h('button', {
      type: 'button', role: 'radio', 'aria-checked': k.key === kind ? 'true' : 'false', class: `kind-pill k-${k.key}` + (k.key === kind ? ' active' : ''),
      onclick: () => { kind = k.key; drawKinds(); },
    }, k.label)));
    drawKinds();
    const body = autoGrow(h('textarea', { class: 'fc', rows: 3, placeholder: '¿Qué has visto / hablado? (Ctrl/⌘+Enter guarda)', 'aria-label': 'Nota', dataset: { draft: '1' } }));
    const blockers = autoGrow(h('textarea', { class: 'fc', rows: 1, placeholder: 'Bloqueos', 'aria-label': 'Bloqueos', dataset: { draft: '1' } }));
    const next = autoGrow(h('textarea', { class: 'fc', rows: 1, placeholder: 'Siguientes pasos', title: 'Se mostrarán en la cabecera de la ficha', 'aria-label': 'Siguientes pasos', dataset: { draft: '1' } }));
    const saveBtn = h('button', { class: 'btn-space-primary btn-sm', type: 'submit' }, 'Guardar nota');
    const form = h('form', { class: 'note-form', onsubmit: (e) => { e.preventDefault(); submit(); } },
      kindPills, body, h('div', { class: 'two' }, blockers, next),
      h('div', { class: 'form-foot' }, h('span', { class: 'dim' }, '🔒 Solo tú ves tus notas · guardar registra la visita para todos'), saveBtn));
    form.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });

    async function submit() {
      const payload = { kind, body: body.value.trim(), blockers: blockers.value.trim(), next_steps: next.value.trim() };
      if (!payload.body && !payload.blockers && !payload.next_steps) { body.focus(); toast('Escribe algo en la nota, bloqueos o siguientes pasos', true); return; }
      saveBtn.disabled = true;
      addNote(currentTeam.id, payload);
      body.value = blockers.value = next.value = ''; [body, blockers, next].forEach((x) => x.dispatchEvent(new Event('input')));
      draw();
      try {
        const upd = await api('POST', `/api/teams/${currentTeam.id}/visit`, {});
        Object.assign(currentTeam, upd || {});
        toast('Nota guardada · visita registrada');
      } catch (e) { toast('Nota guardada en local, pero no se pudo registrar la visita: ' + e.message, true); }
      finally { rerenderHeader(); saveBtn.disabled = false; }
    }

    function draw() {
      const list = teamNotes(currentTeam.id);
      count.textContent = list.length;
      tl.replaceChildren(...(list.length ? list.map(noteItem) : [h('div', { class: 'dim', style: 'font-size:14px;margin-left:-20px' }, 'Sin notas tuyas todavía. Se guardan solo en este navegador.')]));
    }
    function noteItem(n) {
      const d = new Date(n.created_at);
      const item = h('article', { class: `tl-item k-${n.kind}` },
        h('div', { class: 'tl-head' },
          h('span', { class: 'chip ' + (n.kind === 'pitch' ? 'purple' : n.kind === 'mentoria' ? 'cyan' : '') }, kindLabel(n.kind)),
          h('span', { class: 'tl-when', title: fmtFull.format(d) }, h('b', null, fmtDayTime.format(d)), ' · ', h('span', { dataset: { rel: n.created_at } }, relTime(n.created_at))),
          h('span', { class: 'tl-actions' },
            h('button', { class: 'link-btn', type: 'button', onclick: () => edit() }, 'Editar'),
            h('button', { class: 'link-btn danger', type: 'button', onclick: () => del() }, 'Borrar'))),
        n.body ? h('div', { class: 'tl-body' }, n.body) : null,
        n.blockers ? h('div', { class: 'tl-sec blk' }, h('span', { class: 'k' }, 'Bloqueos'), h('span', { class: 'v' }, n.blockers)) : null,
        n.next_steps ? h('div', { class: 'tl-sec nxt' }, h('span', { class: 'k' }, 'Siguientes'), h('span', { class: 'v' }, n.next_steps)) : null);
      async function del() {
        if (!confirm('¿Borrar esta nota?')) return;
        deleteNote(currentTeam.id, n.id); draw(); rerenderHeader(); toast('Nota borrada');
      }
      function edit() {
        const kSel = h('select', { class: 'fc', style: 'width:auto' }, (S.note_kinds || []).map((k) => h('option', { value: k.key, selected: k.key === n.kind }, k.label)));
        const b = autoGrow(h('textarea', { class: 'fc', rows: 3, value: n.body || '', placeholder: 'Nota' }));
        const bl = autoGrow(h('textarea', { class: 'fc', rows: 1, value: n.blockers || '', placeholder: 'Bloqueos' }));
        const nx = autoGrow(h('textarea', { class: 'fc', rows: 1, value: n.next_steps || '', placeholder: 'Siguientes pasos' }));
        const save = () => {
          const data = { kind: kSel.value, body: b.value.trim(), blockers: bl.value.trim(), next_steps: nx.value.trim() };
          if (!data.body && !data.blockers && !data.next_steps) { toast('La nota no puede quedar vacía (usa Borrar)', true); return; }
          updateNote(currentTeam.id, n.id, data); draw(); rerenderHeader(); toast('Nota actualizada');
        };
        const ed = h('article', { class: `tl-item k-${n.kind}`, dataset: { editing: '1' } },
          h('div', { class: 'note-form' }, kSel, b, h('div', { class: 'two' }, bl, nx),
            h('div', { class: 'form-foot' }, h('span', { class: 'dim' }, 'Ctrl/⌘+Enter guarda · Esc cancela'),
              h('button', { class: 'btn-ghost btn-xs', type: 'button', onclick: () => ed.replaceWith(noteItem(n)) }, 'Cancelar'),
              h('button', { class: 'btn-space-primary btn-xs', type: 'button', onclick: save }, 'Guardar'))));
        ed.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
          if (e.key === 'Escape') { e.stopPropagation(); ed.replaceWith(noteItem(n)); }
        });
        item.replaceWith(ed); b.focus();
      }
      return item;
    }
    draw();
    return h('section', { class: 'glass-card panel', dataset: { panel: 'notes' } },
      h('div', { class: 'panel-head' }, h('span', { class: 'panel-title' }, 'Mis notas de sesión'), h('span', { class: 'chip', title: 'Se guardan solo en este navegador. Haz copia desde el menú de datos.' }, '🔒 privadas'), count), form, tl);
  }

  // ---------- Vista: Retos ----------
  function viewChallenges() {
    const list = [...(S.challenges || [])].sort((a, b) => a.num - b.num);
    const head = h('div', { class: 'page-head' },
      h('div', { class: 'grow' }, h('div', { class: 'section-tag' }, `NASA Space Apps 2026 · ${list.length} retos`), h('h2', { class: 'section-title' }, 'Retos oficiales')),
      h('a', { class: 'btn-space-outline btn-sm', href: 'https://www.spaceappschallenge.org/2026/challenges/', target: '_blank', rel: 'noopener noreferrer' }, 'Web oficial ↗'));
    if (!list.length) return h('div', null, head, emptyState('Sin retos cargados', 'Revisa seed.json y reinicia el servidor.'));
    return h('div', null, head, h('div', { class: 'ch-grid' }, list.map((c) => h('article', {
      class: 'glass-card ch-card', tabIndex: 0, onclick: () => go(`#/retos/${c.id}`), onkeydown: (e) => { if (e.key === 'Enter') go(`#/retos/${c.id}`); },
    },
      h('div', { class: 'ch-top' }, h('span', { class: 'num-badge' }, c.num), h('span', { class: 'ch-cat', title: c.category || '' }, c.category || ''),
        h('span', { class: 'ch-teams' + (c.team_count ? ' has' : '') }, c.team_count ? `${c.team_count} equipo${c.team_count > 1 ? 's' : ''}` : 'sin equipos')),
      h('h3', null, c.title),
      c.title_en ? h('div', { class: 'en' }, c.title_en) : null,
      c.summary ? h('p', { class: 'sum' }, c.summary) : null,
      h('div', { class: 'ch-foot' }, difficultyChips(c.difficulty),
        c.url ? h('a', { href: c.url, target: '_blank', rel: 'noopener noreferrer', onclick: (e) => e.stopPropagation() }, 'Ver reto ↗') : null)))));
  }

  async function viewChallenge(id) {
    const c = await api('GET', `/api/challenges/${id}`);
    const teams = (c.teams || []).map((t) => Object.assign({}, S.teams.find((x) => x.id === t.id) || {}, t));
    return h('div', null,
      h('a', { class: 'back', href: '#/retos' }, '← Retos'),
      h('section', { class: 'glass-card ch-detail' },
        h('div', { class: 'row', style: 'gap:10px' }, h('span', { class: 'num-badge' }, c.num), c.category ? h('span', { class: 'ch-cat' }, c.category) : null),
        h('h2', null, c.title),
        c.title_en ? h('div', { class: 'en' }, c.title_en) : null,
        c.summary ? h('p', null, c.summary) : null,
        h('div', { class: 'row', style: 'gap:10px;flex-wrap:wrap' }, difficultyChips(c.difficulty),
          h('span', { style: 'margin-left:auto' }),
          h('button', { class: 'btn-space-outline btn-sm', type: 'button', onclick: () => openNewTeam({ challenge_id: c.id }) }, '+ Equipo con este reto'),
          c.url ? h('a', { class: 'btn-space-primary btn-sm', href: c.url, target: '_blank', rel: 'noopener noreferrer' }, 'Ver reto en NASA ↗') : null)),
      h('div', { class: 'panel-head' }, h('span', { class: 'panel-title' }, 'Equipos que lo trabajan'), h('span', { class: 'count' }, teams.length)),
      teams.length ? h('div', { class: 'mini-grid' }, teams.sort(sortForBoard).map(teamCard))
        : h('div', { class: 'glass-card', style: 'padding:20px' }, h('span', { class: 'muted' }, 'Ningún equipo ha elegido este reto todavía.')));
  }

  // ---------- Vista: Metodologías ----------
  function viewMethods() {
    const list = S.methods || [];
    const head = h('div', { class: 'page-head' },
      h('div', { class: 'grow' }, h('div', { class: 'section-tag' }, 'Caja de herramientas'), h('h2', { class: 'section-title' }, 'Metodologías')));
    if (!list.length) return h('div', null, head, emptyState('Sin metodologías', 'Revisa seed.json y reinicia el servidor.'));
    const index = h('nav', { class: 'glass-card meth-index', 'aria-label': 'Índice' }, list.map((m) => h('a', {
      href: `#/metodologias`, onclick: (e) => { e.preventDefault(); const el = document.getElementById('m-' + m.slug); if (el) el.scrollIntoView({ behavior: 'smooth' }); },
    }, m.name)));
    const cards = list.map((m) => {
      const steps = Array.isArray(m.steps) ? m.steps : [];
      const qs = Array.isArray(m.key_questions) ? m.key_questions : [];
      return h('article', { class: 'glass-card meth', id: 'm-' + m.slug },
        h('h3', null, m.name),
        m.summary ? h('p', { class: 'sum' }, m.summary) : null,
        m.when_to_use ? h('p', { class: 'when' }, h('b', { style: 'color:#ffb37a' }, 'Cuándo usarla: '), m.when_to_use) : null,
        h('div', { class: 'meth-cols' },
          h('div', null, h('div', { class: 'sub c' }, 'Pasos'), steps.length ? h('ol', null, steps.map((s) => h('li', null, s))) : h('span', { class: 'dim' }, '—')),
          h('div', null, h('div', { class: 'sub p' }, 'Preguntas clave'), qs.length ? h('ul', null, qs.map((s) => h('li', null, s))) : h('span', { class: 'dim' }, '—'))),
        m.template ? h('div', { class: 'tpl' }, h('div', { class: 'sub o' }, 'Plantilla'),
          h('pre', null, m.template),
          h('button', { class: 'btn-space-outline btn-xs copy', type: 'button', onclick: () => copyText(m.template) }, 'Copiar')) : null);
    });
    return h('div', null, head, h('div', { class: 'meth-layout' }, index, h('div', { class: 'meth-list' }, cards)));
  }
  async function copyText(txt) {
    try { await navigator.clipboard.writeText(txt); toast('Plantilla copiada'); }
    catch (e) {
      const ta = h('textarea', { style: 'position:fixed;left:-9999px' }); ta.value = txt; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast('Plantilla copiada'); } catch (e2) { toast('No se pudo copiar', true); }
      ta.remove();
    }
  }

  // ---------- Modal: alta rápida ----------
  let modalClose = null;
  function openModal(node, onClose) {
    closeModal();
    const back = h('div', { class: 'modal-back', onmousedown: (e) => { if (e.target === back) closeModal(); } }, node);
    $('#modal-root').replaceChildren(back);
    modalClose = onClose || (() => {});
  }
  function closeModal() { if (!modalClose) return; $('#modal-root').replaceChildren(); const f = modalClose; modalClose = null; f(); }
  const modalOpen = () => !!modalClose;

  function openNewTeam(preset = {}) {
    if (!S) return;
    const prevFocus = document.activeElement;
    const name = h('input', { class: 'fc', placeholder: 'Nombre del equipo', maxlength: 120, 'aria-label': 'Nombre del equipo', style: 'font-size:16px;font-weight:600' });
    const table = h('input', { class: 'fc', placeholder: 'Ej. A7', 'aria-label': 'Mesa', style: 'text-align:center;font-weight:700' });
    const ch = h('select', { class: 'fc', 'aria-label': 'Reto' }, challengeOptions(preset.challenge_id || null, '— Reto (puede decidirse luego) —'));
    const idea = h('input', { class: 'fc', placeholder: 'Idea en una frase (opcional)', 'aria-label': 'Idea' });
    const rows = h('div', { class: 'mem-rows' });
    const addRow = (focus = true) => {
      const n = h('input', { class: 'fc', placeholder: 'Nombre', 'aria-label': 'Nombre del miembro' });
      const r = h('select', { class: 'fc', 'aria-label': 'Rol' }, roleOptions('otro'));
      const s = h('input', { class: 'fc', placeholder: 'Skills', 'aria-label': 'Skills' });
      const row = h('div', { class: 'mem-row' }, n, r, s, h('button', { class: 'link-btn danger', type: 'button', title: 'Quitar fila', onclick: () => { row.remove(); if (!rows.children.length) addRow(); } }, '✕'));
      for (const el of [n, r, s]) el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          const isLast = row === rows.lastElementChild;
          if (!n.value.trim()) { n.focus(); return; }
          if (isLast) addRow(); else $('input', row.nextElementSibling).focus();
        }
      });
      rows.appendChild(row);
      if (focus) n.focus();
    };
    addRow(false);
    // Enter en campos superiores salta al siguiente
    const order = [name, table, ch, idea];
    order.forEach((el, i) => el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); (order[i + 1] || $('input', rows)).focus(); }
    }));
    const saveBtn = h('button', { class: 'btn-space-primary', type: 'button', onclick: () => save() }, 'Crear equipo');
    async function save() {
      if (!name.value.trim()) { name.focus(); flash(name, 'err'); toast('El nombre del equipo es obligatorio', true); return; }
      const members = $$('.mem-row', rows).map((r) => {
        const [n, ro, s] = $$('input,select', r);
        return { name: n.value.trim(), role: ro.value, skills: s.value.trim() };
      }).filter((m) => m.name);
      const body = { name: name.value.trim(), table_label: table.value.trim(), idea: idea.value.trim(), challenge_id: ch.value ? +ch.value : null, phase: 'idea', members };
      saveBtn.disabled = true;
      try {
        const t = await api('POST', '/api/teams', body);
        modalClose = null; $('#modal-root').replaceChildren();
        toast(`Equipo «${t.name}» creado`);
        go(`#/equipos/${t.id}`);
      } catch (e) { toast(e.message, true); saveBtn.disabled = false; }
    }
    const modal = h('div', { class: 'glass-card modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'nt-title' },
      h('div', { class: 'modal-head' },
        h('div', null, h('div', { class: 'section-tag', style: 'margin-bottom:6px' }, 'Alta rápida'), h('h2', { class: 'section-title', id: 'nt-title', style: 'font-size:1.25rem' }, 'Nuevo equipo')),
        h('button', { class: 'icon-btn x', type: 'button', title: 'Cerrar (Esc)', 'aria-label': 'Cerrar', onclick: closeModal }, '✕')),
      h('div', { class: 'grid2' },
        h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Nombre *'), name),
        h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Mesa'), table)),
      h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Reto oficial'), ch),
      h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Idea'), idea),
      h('div', { class: 'field', style: 'margin-bottom:0' },
        h('label', { class: 'lbl' }, 'Miembros', h('span', { class: 'hint' }, 'Enter añade otra fila')),
        rows,
        h('button', { class: 'link-btn', type: 'button', style: 'margin-top:6px;color:var(--primary-cyan)', onclick: () => addRow() }, '+ Añadir miembro')),
      h('div', { class: 'modal-foot' },
        h('span', { class: 'dim' }, h('kbd', null, 'Ctrl'), '/', h('kbd', null, '⌘'), '+', h('kbd', null, 'Enter'), ' crea · ', h('kbd', null, 'Esc'), ' cierra'),
        h('span', { class: 'sp' }),
        h('button', { class: 'btn-ghost', type: 'button', onclick: closeModal }, 'Cancelar'),
        saveBtn));
    modal.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); } });
    openModal(modal, () => { if (prevFocus && prevFocus.focus) prevFocus.focus(); });
    name.focus();
  }

  // ---------- Búsqueda global ----------
  function searchLocalNotes(q) {
    const lq = q.toLowerCase(), out = [];
    const nameOf = (id) => ((S && S.teams || []).find((t) => String(t.id) === String(id)) || {}).name;
    for (const tid of Object.keys(PN.teams)) {
      const team_name = nameOf(tid);
      if (!team_name) continue;   // equipo borrado
      for (const n of PN.teams[tid]) {
        if ([n.body, n.blockers, n.next_steps].some((x) => (x || '').toLowerCase().includes(lq))) out.push(Object.assign({ team_id: +tid, team_name }, n));
      }
    }
    return out.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')).slice(0, 20);
  }
  function setupSearch() {
    const input = $('#search-input'), box = $('#search-results');
    let timer = null, seq = 0, items = [], sel = -1;
    const close = () => { box.hidden = true; sel = -1; };
    const choose = (i) => { const it = items[i]; if (!it) return; close(); input.value = ''; input.blur(); go(it.href); };
    const mark = () => items.forEach((it, i) => it.el.classList.toggle('sel', i === sel));
    async function run() {
      const q = input.value.trim();
      if (q.length < 1) { close(); return; }
      const my = ++seq;
      let r;
      try { r = await api('GET', '/api/search?q=' + encodeURIComponent(q)); } catch (e) { toast(e.message, true); return; }
      if (my !== seq) return;
      items = []; sel = -1;
      const groups = [];
      const mk = (href, main, sub) => {
        const el = h('button', { class: 'sr-item', type: 'button', role: 'option', onmousedown: (e) => e.preventDefault(), onclick: () => choose(items.indexOf(it)) },
          h('div', { class: 'sr-main' }, main), sub ? h('div', { class: 'sr-sub' }, sub) : null);
        const it = { el, href }; items.push(it); return el;
      };
      if (r.teams && r.teams.length) groups.push(h('div', { class: 'sr-group' }, 'Equipos'), r.teams.map((t) => mk(`#/equipos/${t.id}`, highlight(t.name, q),
        [t.table_label ? `Mesa ${t.table_label} · ` : '', phaseLabel(t.phase), t.idea ? ' · ' : '', highlight(snippet(t.idea, q, 70), q)])));
      if (r.members && r.members.length) groups.push(h('div', { class: 'sr-group' }, 'Miembros'), r.members.map((m) => mk(`#/equipos/${m.team_id}`, highlight(m.name, q),
        [m.team_name || '', ' · ', roleLabel(m.role), m.skills ? ' · ' : '', highlight(snippet(m.skills, q, 60), q)])));
      r.notes = searchLocalNotes(q);
      if (r.notes && r.notes.length) groups.push(h('div', { class: 'sr-group' }, 'Mis notas'), r.notes.map((n) => mk(`#/equipos/${n.team_id}`, [n.team_name || 'Equipo', h('span', { class: 'dim', style: 'font-weight:400' }, ' · ' + fmtDayTime.format(new Date(n.created_at)))],
        highlight(snippet([n.body, n.blockers, n.next_steps].filter(Boolean).join(' · '), q), q))));
      box.replaceChildren(...(groups.length ? groups.flat() : [h('div', { class: 'sr-empty' }, 'Sin resultados para «', q, '»')]));
      box.hidden = false;
      if (items.length) { sel = 0; mark(); }
    }
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 160); });
    input.addEventListener('focus', () => { if (input.value.trim()) run(); });
    input.addEventListener('blur', () => setTimeout(close, 120));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (items.length) { sel = (sel + 1) % items.length; mark(); items[sel].el.scrollIntoView({ block: 'nearest' }); } }
      else if (e.key === 'ArrowUp') { e.preventDefault(); if (items.length) { sel = (sel - 1 + items.length) % items.length; mark(); items[sel].el.scrollIntoView({ block: 'nearest' }); } }
      else if (e.key === 'Enter') { e.preventDefault(); if (box.hidden) run(); else choose(sel < 0 ? 0 : sel); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (!box.hidden && input.value) { input.value = ''; close(); } else input.blur(); }
    });
  }

  // ---------- Exportar / importar ----------
  function setupData() {
    const btn = $('#data-btn'), menu = $('#data-menu'), file = $('#import-file');
    const setOpen = (o) => { menu.hidden = !o; btn.setAttribute('aria-expanded', o ? 'true' : 'false'); };
    btn.addEventListener('click', (e) => { e.stopPropagation(); setOpen(menu.hidden); });
    document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) setOpen(false); });
    $('#export-link').addEventListener('click', () => { setOpen(false); toast('Exportando equipos…'); });
    $('#import-btn').addEventListener('click', () => { setOpen(false); file.value = ''; file.click(); });
    $('#wipe-btn').addEventListener('click', async () => {
      setOpen(false);
      const n = (S && S.teams || []).length;
      if (prompt(`Vas a BORRAR los ${n} equipos y sus miembros para TODOS los mentores.\nExporta antes una copia si la necesitas.\n\nEscribe BORRAR para confirmar:`) !== 'BORRAR') { toast('Cancelado'); return; }
      try { await api('POST', '/api/import', { version: 2, teams: [], members: [] }); PN.teams = {}; PN.members = {}; savePN(); toast('Equipos vaciados'); currentTeam = null; go('#/'); }
      catch (e) { toast(e.message, true); }
    });
    const pnFile = $('#import-notes-file');
    $('#export-notes-btn').addEventListener('click', () => { setOpen(false); exportPN(); toast('Copia de tus notas descargada'); });
    $('#import-notes-btn').addEventListener('click', () => { setOpen(false); pnFile.value = ''; pnFile.click(); });
    pnFile.addEventListener('change', async () => {
      const f = pnFile.files && pnFile.files[0];
      if (!f) return;
      try { const n = importPN(JSON.parse(await f.text())); toast(`${n} notas recuperadas`); render({ keepScroll: true }); }
      catch (e) { toast(e.message || 'Fichero no válido', true); }
    });
    file.addEventListener('change', async () => {
      const f = file.files && file.files[0];
      if (!f) return;
      let data;
      try { data = JSON.parse(await f.text()); } catch (e) { toast('El fichero no es un JSON válido', true); return; }
      const n = Array.isArray(data.teams) ? data.teams.length : '?';
      if (!confirm(`Importar «${f.name}» (${n} equipos) REEMPLAZARÁ todos los equipos y miembros PARA TODOS LOS MENTORES.\n\nConsejo: exporta antes una copia. ¿Continuar?`)) return;
      try { const r = await api('POST', '/api/import', data); toast(`Importados ${r && r.teams != null ? r.teams : n} equipos`); currentTeam = null; go('#/'); }
      catch (e) { toast(e.message, true); }
    });
  }

  // ---------- Telemetría: reloj + cuenta atrás ----------
  function tickClock() {
    const now = Date.now();
    $('#tele-clock').textContent = fmtTime.format(new Date(now));
    const d = PITCH_AT - now, el = $('#tele-count'), pill = $('#telemetry');
    if (d <= 0) { el.textContent = d > -3 * 3600e3 ? 'PITCH FINAL EN CURSO' : 'MISIÓN COMPLETADA'; pill.classList.add('urgent'); return; }
    const s = Math.floor(d / 1000), days = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    const p2 = (x) => String(x).padStart(2, '0');
    el.textContent = 'PITCH T−' + (days ? `${days}d ` : '') + `${p2(hh)}:${p2(mm)}:${p2(ss)}`;
    pill.classList.toggle('urgent', d < 3 * 3600e3);
  }

  // ---------- Refresco automático ----------
  function isEditing() {
    const a = document.activeElement;
    if (a && a.matches && a.matches('input, textarea, select, [contenteditable]') && $('#app').contains(a)) return true;
    if ($('[data-editing]')) return true;
    if ($$('[data-draft]').some((t) => t.value.trim())) return true;
    return false;
  }
  async function autoRefresh() {
    refreshRelTimes();
    if (document.hidden || dragging || modalOpen() || isEditing() || !ME.logged_in) return;
    if (route.name === 'ficha' && currentTeam) {
      // la ficha solo se repinta si otro mentor la cambió y no estás escribiendo
      try {
        await loadState();
        const fresh = (S.teams || []).find((t) => t.id === currentTeam.id);
        if (!fresh) { toast('Otro mentor ha borrado este equipo', true); currentTeam = null; go('#/'); return; }
        if (fresh.updated_at !== currentTeam.updated_at || fresh.last_visit_at !== currentTeam.last_visit_at) await render({ keepScroll: true, reload: false });
      } catch (e) { /* silencioso */ }
      return;
    }
    try { await render({ keepScroll: true }); } catch (e) { /* silencioso */ }
  }

  // ---------- Atajos de teclado ----------
  function setupKeys() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modalOpen()) { e.preventDefault(); closeModal(); return; }
      if (e.key === 'Escape' && !$('#data-menu').hidden) { $('#data-menu').hidden = true; return; }
      const tgt = e.target;
      const typing = tgt && tgt.matches && tgt.matches('input, textarea, select, [contenteditable]');
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === '/') { e.preventDefault(); $('#search-input').focus(); $('#search-input').select(); }
      else if ((e.key === 'n' || e.key === 'N') && !modalOpen()) { e.preventDefault(); openNewTeam(); }
    });
  }

  // ---------- Login (contraseña común de mentores) ----------
  function showLogin(msg) {
    if ($('#login-back')) return;
    const name = h('input', { class: 'fc', placeholder: 'Tu nombre (lo verán los demás mentores)', maxlength: 40, 'aria-label': 'Tu nombre', value: prefs.lastName || '' });
    const pass = h('input', { class: 'fc', type: 'password', placeholder: 'Contraseña de mentores', 'aria-label': 'Contraseña' });
    const err = h('div', { class: 'dim', style: 'color:#ff8a8a;min-height:20px;font-size:14px' }, msg || '');
    const btn = h('button', { class: 'btn-space-primary', type: 'submit' }, 'Entrar');
    const form = h('form', { class: 'glass-card modal', style: 'max-width:420px', onsubmit: async (e) => {
      e.preventDefault();
      if (!name.value.trim()) { name.focus(); err.textContent = 'Escribe tu nombre.'; return; }
      btn.disabled = true; err.textContent = '';
      try {
        const r = await api('POST', '/api/login', { name: name.value, password: pass.value });
        ME = { auth_required: true, logged_in: true, name: r.name };
        prefs.lastName = r.name; savePrefs();
        $('#login-back').remove(); paintMe(); render();
      } catch (e2) { err.textContent = e2.message; pass.select(); }
      finally { btn.disabled = false; }
    } },
      h('div', { class: 'section-tag', style: 'margin-bottom:6px' }, 'Space Apps Valencia 2026'),
      h('h2', { class: 'section-title', style: 'font-size:1.3rem;margin-bottom:14px' }, 'Acceso mentores'),
      h('div', { class: 'field' }, name), h('div', { class: 'field' }, pass), err,
      h('p', { class: 'dim', style: 'font-size:13px;margin:6px 0 14px' }, 'Los equipos son compartidos. Tus notas se guardan solo en este navegador.'),
      h('div', { class: 'modal-foot' }, h('span', { class: 'sp' }), btn));
    document.body.appendChild(h('div', { class: 'modal-back', id: 'login-back', style: 'z-index:1000' }, form));
    (name.value ? pass : name).focus();
  }
  function paintMe() {
    const box = $('#me-box');
    if (!ME.auth_required) { box.hidden = true; return; }
    box.hidden = false;
    box.replaceChildren(
      h('span', { class: 'me-name', title: 'Conectado como ' + ME.name }, ME.name || '—'),
      h('button', { class: 'link-btn', type: 'button', onclick: async () => {
        try { await api('POST', '/api/logout', {}); } catch (e) { /* */ }
        ME.logged_in = false; S = null; $('#app').replaceChildren(); showLogin();
      } }, 'Salir'));
  }

  // ---------- Arranque ----------
  async function init() {
    $('#new-team-btn').addEventListener('click', () => openNewTeam());
    setupSearch(); setupData(); setupKeys();
    tickClock(); setInterval(tickClock, 1000);
    setInterval(autoRefresh, REFRESH_MS);
    setInterval(refreshRelTimes, 20000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshRelTimes(); });
    window.addEventListener('hashchange', () => { closeModal(); render(); });
    $('#app').replaceChildren(h('div', { class: 'loading' }, 'CONECTANDO CON LA BASE…'));
    try { ME = await api('GET', '/api/me'); } catch (e) { /* render mostrará el error */ }
    paintMe();
    if (ME.auth_required && !ME.logged_in) { $('#app').replaceChildren(); showLogin(); return; }
    render();
  }
  init();
})();
