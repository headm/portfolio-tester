/* Portfolio backtester UI.
   Series colors come from CSS custom properties so light/dark swap in one place
   and the JS never hard-codes a hex. */

const $ = (sel, root = document) => root.querySelector(sel);
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const css = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();
const SLOTS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6'];
const MAX_PORTFOLIOS = SLOTS.length;

const state = {
  portfolios: [],
  result: null,
  mode: 'balance',
  axis: 'log',
  rollingYears: null,
  projFocus: null,
  seq: 0,
};

/* ---------------------------------------------------------------- format */
const fmtMoney = (v) =>
  v == null ? '—' : v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const fmtMoney2 = (v) =>
  v == null ? '—' : v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const fmtPct = (v, d = 2) => (v == null || !isFinite(v) ? '—' : (v * 100).toFixed(d) + '%');
const fmtNum = (v, d = 2) => (v == null || !isFinite(v) ? '—' : v.toFixed(d));
const fmtDate = (iso) =>
  !iso ? '—' : new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
const toTs = (iso) => Date.parse(iso + 'T00:00:00Z') / 1000;

/* ------------------------------------------------------------- portfolios */
/* A portfolio keeps its colour for life. Deriving colour from list position
   would repaint every existing series the moment a new card is inserted at the
   top, which breaks the one thing a comparison chart has to guarantee: that a
   colour means the same portfolio from one run to the next. */
function nextFreeSlot() {
  const used = new Set(state.portfolios.map((p) => p.slot));
  for (let i = 0; i < MAX_PORTFOLIOS; i++) if (!used.has(i)) return i;
  return 0;
}

function makePortfolio(seed = {}) {
  return {
    id: ++state.seq,
    slot: nextFreeSlot(),
    name: seed.name || `Portfolio ${state.seq}`,
    holdings: seed.weights
      ? Object.entries(seed.weights).map(([symbol, weight]) => ({ symbol, weight }))
      : [{ symbol: '', weight: 100 }],
    rebalance: seed.rebalance || 'none',
    threshold_pct: 5,
    // One cash-flow setting rather than two: paying in and drawing down are
    // opposite phases of a plan, and the engine rejects doing both at once.
    flow: { mode: 'none', amount: 500, rate: 4, cadence: 'monthly' },
  };
}

function colorFor(slot) { return css(SLOTS[slot % SLOTS.length]); }

/* What actually changes a backtest. Renaming deliberately does not count --
   it would be obnoxious to grey a card out over a typo fix. */
function specOf(p) {
  return JSON.stringify({
    w: p.holdings
      .filter((h) => h.symbol.trim())
      .map((h) => [h.symbol.trim().toUpperCase(), parseFloat(h.weight) || 0])
      .sort(),
    r: p.rebalance,
    t: p.threshold_pct,
    c: [p.flow.mode, p.flow.amount, p.flow.rate, p.flow.cadence],
  });
}

const isPending = (p) => p.ran !== specOf(p);

function updateRunButton() {
  if (typeof updateStale === 'function') updateStale();
}

/* Update one card's live indicators without a full re-render, so typing in a
   weight box does not tear down the field being typed into. */
function syncCard(el, p) {
  const sum = p.holdings.reduce((a, h) => a + (parseFloat(h.weight) || 0), 0);
  const tag = el.querySelector('.weight-sum');
  tag.textContent = `Weights: ${sum.toFixed(1)}%`;
  tag.classList.toggle('off', Math.abs(sum - 100) > 0.01);
  el.classList.toggle('pending', isPending(p));
  updateRunButton();
  save();
}

function renderCards() {
  save();
  const host = $('#cards');
  host.innerHTML = '';
  state.portfolios.forEach((p) => host.appendChild(cardEl(p)));
  $('#add').disabled = state.portfolios.length >= MAX_PORTFOLIOS;
  updateRunButton();
}

function cardEl(p) {
  const el = document.createElement('div');
  el.className = 'card' + (isPending(p) ? ' pending' : '');
  el.style.setProperty('--accent', colorFor(p.slot));

  const sum = p.holdings.reduce((a, h) => a + (parseFloat(h.weight) || 0), 0);
  const rows = p.holdings.map((h, i) => `
    <div class="holding" data-i="${i}">
      <input class="sym" value="${h.symbol}" placeholder="TICKER" spellcheck="false" list="symlist">
      <input class="wt" type="number" min="0" step="1" value="${h.weight}">
      <span class="pct">%</span>
      <button type="button" class="danger" data-act="rm-holding" title="Remove holding">&times;</button>
    </div>`).join('');

  el.innerHTML = `
    <div class="card-head">
      <input class="name" value="${p.name}">
      <button type="button" class="danger" data-act="dup" title="Duplicate portfolio">⧉</button>
      <button type="button" class="danger" data-act="rm" title="Remove portfolio">&times;</button>
    </div>
    ${rows}
    <button type="button" class="ghost" data-act="add-holding">+ Add holding</button>
    <div class="card-row">
      <label class="field"><span>Rebalance</span>
        <select class="rebal">
          ${['none', 'monthly', 'quarterly', 'annual', 'threshold'].map(v =>
            `<option value="${v}" ${p.rebalance === v ? 'selected' : ''}>${
              { none: 'Never (drift)', monthly: 'Monthly', quarterly: 'Quarterly',
                annual: 'Annually', threshold: 'On drift band' }[v]}</option>`).join('')}
        </select>
      </label>
      ${p.rebalance === 'threshold'
        ? `<label class="field"><span>Band ±%</span><input class="thresh" type="number" min="1" step="1" value="${p.threshold_pct}"></label>`
        : ''}
    </div>
    <div class="card-row">
      <label class="field"><span>Cash flow</span>
        <select class="flowmode">
          ${[['none', 'None'], ['contribute', 'Contribute'], ['withdraw', 'Withdraw']].map(([v, t]) =>
            `<option value="${v}" ${p.flow.mode === v ? 'selected' : ''}>${t}</option>`).join('')}
        </select>
      </label>
      ${p.flow.mode === 'contribute'
        ? `<label class="field"><span>Amount</span><input class="flowamt" type="number" min="0" step="50" value="${p.flow.amount}"></label>`
        : ''}
      ${p.flow.mode === 'withdraw'
        ? `<label class="field"><span>% per year</span><input class="flowrate" type="number" min="0" max="100" step="0.1" value="${p.flow.rate}"></label>`
        : ''}
    </div>
    ${p.flow.mode === 'none' ? '' : `
    <div class="card-row">
      <label class="field"><span>Cadence</span>
        <select class="cadence">
          ${['monthly', 'quarterly', 'annual'].map(v =>
            `<option value="${v}" ${p.flow.cadence === v ? 'selected' : ''}>${v[0].toUpperCase() + v.slice(1)}</option>`).join('')}
        </select>
      </label>
    </div>
    ${p.flow.mode === 'withdraw'
      ? `<p class="fieldnote">${p.flow.rate}% of the starting balance per year, raised with
         inflation — the "safe withdrawal rate" test.</p>`
      : ''}`}
    <div class="card-foot">
      <span class="weight-sum ${Math.abs(sum - 100) > 0.01 ? 'off' : ''}">Weights: ${sum.toFixed(1)}%</span>
      <button type="button" class="ghost" data-act="normalize">Normalize to 100%</button>
    </div>`;

  // -- wiring
  el.querySelector('.name').oninput = (e) => { p.name = e.target.value; };
  el.querySelector('.rebal').onchange = (e) => { p.rebalance = e.target.value; renderCards(); };
  const th = el.querySelector('.thresh');
  if (th) th.oninput = (e) => { p.threshold_pct = parseFloat(e.target.value) || 5; syncCard(el, p); };
  el.querySelector('.flowmode').onchange = (e) => { p.flow.mode = e.target.value; renderCards(); };
  const amt = el.querySelector('.flowamt');
  if (amt) amt.oninput = (e) => { p.flow.amount = parseFloat(e.target.value) || 0; syncCard(el, p); };
  const rate = el.querySelector('.flowrate');
  if (rate) rate.oninput = (e) => { p.flow.rate = parseFloat(e.target.value) || 0; syncCard(el, p); };
  const cad = el.querySelector('.cadence');
  if (cad) cad.onchange = (e) => { p.flow.cadence = e.target.value; syncCard(el, p); };

  el.querySelectorAll('.holding').forEach((row) => {
    const i = +row.dataset.i;
    row.querySelector('.sym').oninput = (e) => {
      p.holdings[i].symbol = e.target.value.toUpperCase();
      syncCard(el, p);
    };
    row.querySelector('.sym').onblur = (e) => { if (e.target.value.trim()) suggest(e.target.value); };
    row.querySelector('.wt').oninput = (e) => {
      p.holdings[i].weight = e.target.value;
      syncCard(el, p);
    };
  });

  el.onclick = (e) => {
    const act = e.target.dataset.act;
    if (!act) return;
    if (act === 'rm') state.portfolios = state.portfolios.filter((x) => x.id !== p.id);
    if (act === 'dup' && state.portfolios.length < MAX_PORTFOLIOS) {
      const copy = JSON.parse(JSON.stringify(p));
      copy.id = ++state.seq;
      copy.slot = nextFreeSlot();
      copy.name = p.name + ' (copy)';
      delete copy.ran;   // a copy is not in the chart until it is run
      // Kept next to its source: the whole point of duplicating is to compare
      // the two side by side.
      state.portfolios.splice(state.portfolios.indexOf(p) + 1, 0, copy);
    }
    if (act === 'add-holding') p.holdings.push({ symbol: '', weight: 0 });
    if (act === 'rm-holding') {
      const i = +e.target.closest('.holding').dataset.i;
      p.holdings.splice(i, 1);
      if (!p.holdings.length) p.holdings.push({ symbol: '', weight: 100 });
    }
    if (act === 'normalize') {
      const s = p.holdings.reduce((a, h) => a + (parseFloat(h.weight) || 0), 0);
      if (s > 0) p.holdings.forEach((h) => { h.weight = +((parseFloat(h.weight) || 0) * 100 / s).toFixed(2); });
      else p.holdings.forEach((h) => { h.weight = +(100 / p.holdings.length).toFixed(2); });
    }
    renderCards();
  };
  return el;
}

/* ------------------------------------------------------------ ticker hints */
const symCache = new Set();
async function suggest(q) {
  try {
    const r = await fetch('/api/search?q=' + encodeURIComponent(q));
    const list = await r.json();
    const dl = $('#symlist') || Object.assign(document.createElement('datalist'), { id: 'symlist' });
    if (!dl.parentNode) document.body.appendChild(dl);
    list.forEach((s) => {
      if (symCache.has(s.symbol)) return;
      symCache.add(s.symbol);
      const o = document.createElement('option');
      o.value = s.symbol;
      o.label = s.name || '';
      dl.appendChild(o);
    });
  } catch (_) { /* hints are optional */ }
}

/* --------------------------------------------------- persistence & sharing */
const STORE_KEY = 'backtester.state.v1';
const GLOBAL_INPUTS = ['initial', 'benchmark', 'start', 'end',
                       'commission', 'slippage', 'expense', 'rf', 'project'];

function snapshot() {
  const g = {};
  GLOBAL_INPUTS.forEach((id) => { g[id] = $('#' + id).value; });
  g.real = $('#real').checked;
  return {
    v: 1,
    portfolios: state.portfolios.map((p) => ({
      name: p.name, slot: p.slot, holdings: p.holdings,
      rebalance: p.rebalance, threshold_pct: p.threshold_pct, flow: p.flow,
    })),
    globals: g,
    ui: { mode: state.mode, axis: state.axis, rolling: state.rollingYears },
  };
}

function applySnapshot(snap) {
  if (!snap || !Array.isArray(snap.portfolios) || !snap.portfolios.length) return false;
  try {
    Object.entries(snap.globals || {}).forEach(([id, v]) => {
      const el = $('#' + id);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v; else el.value = v;
    });
    state.portfolios = snap.portfolios.slice(0, MAX_PORTFOLIOS).map((p, i) => ({
      id: ++state.seq,
      slot: Number.isInteger(p.slot) ? p.slot : i,
      name: p.name || `Portfolio ${i + 1}`,
      holdings: (p.holdings || []).map((h) => ({ symbol: h.symbol || '', weight: h.weight })),
      rebalance: p.rebalance || 'none',
      threshold_pct: p.threshold_pct || 5,
      flow: Object.assign({ mode: 'none', amount: 500, rate: 4, cadence: 'monthly' }, p.flow || {}),
    })).filter((p) => p.holdings.length);
    // Restored dates are explicit, so no horizon chip should claim credit for
    // them unless it actually matches.
    syncHorizonChips();
    if (snap.ui) {
      state.mode = snap.ui.mode || state.mode;
      state.axis = snap.ui.axis || state.axis;
      state.rollingYears = snap.ui.rolling ?? state.rollingYears;
    }
    return state.portfolios.length > 0;
  } catch (_) {
    return false;
  }
}

const save = debounce(() => {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(snapshot())); } catch (_) {}
}, 300);

/* URL-safe base64 of the snapshot, so a comparison can be bookmarked or sent
   to someone. Kept in the hash so it never reaches the server. */
function encodeState(obj) {
  const bytes = new TextEncoder().encode(JSON.stringify(obj));
  let bin = '';
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function decodeState(text) {
  const bin = atob(text.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

function loadSaved() {
  const hash = location.hash.replace(/^#s=/, '');
  if (hash) {
    try {
      if (applySnapshot(decodeState(hash))) return true;
    } catch (_) {
      message('warn', 'That shared link could not be read — starting fresh.');
    }
  }
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return applySnapshot(JSON.parse(raw));
  } catch (_) {}
  return false;
}

/* ------------------------------------------------------- local data status */
async function loadStatus() {
  try {
    const st = await (await fetch('/api/status')).json();
    const el = $('#datastatus');
    if (!st.last_price_date) {
      el.textContent = 'Prices download the first time you run a backtest.';
      return;
    }
    const cpi = st.cpi_available ? '' : ' · inflation data unavailable';
    el.innerHTML = st.stale
      ? `<span class="warnpip">Prices are ${st.days_stale} days old</span> ` +
        `(through ${fmtDate(st.last_price_date)})${cpi}`
      : `Prices through ${fmtDate(st.last_price_date)}${cpi}`;
  } catch (_) {
    $('#datastatus').textContent = 'Could not read local data status.';
  }
}

async function refreshPrices() {
  const btn = $('#refresh');
  btn.disabled = true;
  btn.textContent = 'Updating…';
  try {
    const res = await (await fetch('/api/refresh', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' })).json();
    const failed = Object.keys(res.failed || {});
    if (failed.length) message('warn', `Could not update: ${failed.join(', ')}`);
    await loadStatus();
    if (state.result) run();
  } catch (err) {
    message('error', 'Update failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Update prices';
  }
}

/* ------------------------------------------------------------------- run */
function settings() {
  return {
    initial: parseFloat($('#initial').value) || 10000,
    start: $('#start').value || null,
    end: $('#end').value || null,
    commission: parseFloat($('#commission').value) || 0,
    slippage_bps: parseFloat($('#slippage').value) || 0,
    expense_ratio_pct: parseFloat($('#expense').value) || 0,
    rf_pct: parseFloat($('#rf').value) || 0,
    real: $('#real').checked,
    project_years: parseFloat($('#project').value) || 0,
  };
}

/* The settings that apply to every portfolio at once -- starting amount, dates,
   benchmark and costs. When one of these changes the drawn chart is stale even
   though no card was touched, so the UI has to say so. */
const globalSignature = () => JSON.stringify([settings(), $('#benchmark').value.trim()]);

/* One signal for "the chart no longer matches the controls", whether that came
   from a global setting or from adding or editing a portfolio. */
function updateStale() {
  const stale = state.result != null &&
    (state.ranGlobals !== globalSignature() || state.portfolios.some(isPending));
  $('#stale').hidden = !stale;
  $('#run').classList.toggle('has-pending', stale);
  return stale;
}

function message(kind, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + kind;
  el.innerHTML = `<span class="ico">${kind === 'error' ? '✕' : '!'}</span><span>${text}</span>`;
  $('#messages').appendChild(el);
}

async function run() {
  const btn = $('#run');
  btn.disabled = true;
  btn.textContent = 'Running…';
  $('#messages').innerHTML = '';
  $('#stale').hidden = true;

  // Snapshot the list: the rail can be edited while the request is in flight.
  const submitted = state.portfolios.slice();
  const payload = {
    settings: settings(),
    benchmark: $('#benchmark').value.trim() || null,
    portfolios: submitted.map((p) => ({
      name: p.name,
      weights: Object.fromEntries(
        p.holdings.filter((h) => h.symbol.trim()).map((h) => [h.symbol.trim(), parseFloat(h.weight) || 0])
      ),
      rebalance: p.rebalance,
      threshold_pct: p.threshold_pct,
      contribution: p.flow.mode === 'contribute'
        ? { amount: p.flow.amount, cadence: p.flow.cadence } : null,
      withdrawal: p.flow.mode === 'withdraw'
        ? { rate_pct: p.flow.rate, cadence: p.flow.cadence } : null,
    })),
  };
  const globalsAtSubmit = globalSignature();

  try {
    const resp = await fetch('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Backtest failed');
    data.slots = submitted.map((p) => p.slot);
    state.result = data;
    state.ranGlobals = globalsAtSubmit;
    submitted.forEach((p) => { p.ran = specOf(p); });
    (data.warnings || []).forEach((w) => message('warn', w));
    renderResults();
    renderCards();
  } catch (err) {
    message('error', err.message);
    $('#output').hidden = true;
    $('#empty').hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run Test';
  }
}

/* --------------------------------------------------------------- charting */
let uEquity = null;
let uDraw = null;

function seriesList() {
  // Slots are captured when the run is submitted, so editing the rail afterwards
  // cannot re-colour a chart that is already drawn.
  const slots = state.result.slots || [];
  const out = state.result.portfolios.map((p, i) => ({ ...p, color: colorFor(slots[i] ?? i) }));
  if (state.result.benchmark) out.push({ ...state.result.benchmark, color: css('--bench'), dash: [5, 4] });
  return out;
}

/* Portfolios can have different trading days (different holdings), so align
   everything onto the union of dates and let uPlot draw gaps for missing ones. */
function alignSeries(list, key) {
  const all = new Set();
  list.forEach((s) => s.dates.forEach((d) => all.add(d)));
  const dates = [...all].sort();
  const xs = dates.map(toTs);
  const ys = list.map((s) => {
    const m = new Map();
    s.dates.forEach((d, i) => m.set(d, s[key][i]));
    return dates.map((d) => (m.has(d) ? m.get(d) : null));
  });
  return { dates, data: [xs, ...ys] };
}

function tooltipPlugin(list, fmt) {
  let tip;
  return {
    hooks: {
      init: (u) => {
        tip = document.createElement('div');
        tip.className = 'tip';
        tip.style.display = 'none';
        u.over.appendChild(tip);
      },
      setCursor: (u) => {
        const { idx, left, top } = u.cursor;
        if (idx == null || left < 0) { tip.style.display = 'none'; updateLegend(null); return; }
        const when = new Date(u.data[0][idx] * 1000).toISOString().slice(0, 10);
        const rows = list.map((s, i) => {
          const v = u.data[i + 1][idx];
          if (v == null) return '';
          return `<div class="row"><span class="nm"><span class="sw" style="background:${s.color}"></span>${s.name}</span><span class="vl">${fmt(v)}</span></div>`;
        }).join('');
        tip.innerHTML = `<div class="when">${fmtDate(when)}</div>${rows}`;
        tip.style.display = 'block';
        const w = tip.offsetWidth;
        tip.style.left = Math.min(left + 14, u.over.clientWidth - w - 6) + 'px';
        tip.style.top = Math.max(top - 10, 4) + 'px';
        updateLegend(idx);
      },
      setSize: (u) => { if (tip) tip.style.display = 'none'; },
    },
  };
}

function axisTheme() {
  return {
    stroke: css('--muted'),
    grid: { stroke: css('--grid'), width: 1 },
    ticks: { stroke: css('--grid'), width: 1, size: 4 },
    font: '11px ' + css('--sans'),
  };
}

/* Clean log ticks. uPlot's own log splits land on values like 10051 and 30153
   once a custom range is supplied, which makes for ugly labels and defeats any
   attempt to thin them by mantissa. Generating them directly is simpler and
   always produces round numbers. */
function logSplits(u, axisIdx, scaleMin, scaleMax) {
  const build = (mantissas) => {
    const out = [];
    for (let e = Math.floor(Math.log10(scaleMin)); e <= Math.ceil(Math.log10(scaleMax)); e++) {
      for (const m of mantissas) {
        const v = m * Math.pow(10, e);
        if (v >= scaleMin && v <= scaleMax) out.push(v);
      }
    }
    return out;
  };
  let ticks = build([1, 2, 3, 5]);
  if (ticks.length < 4) ticks = build([1, 1.5, 2, 2.5, 3, 4, 5, 7]);
  if (ticks.length < 3) ticks = build([1, 1.2, 1.4, 1.6, 1.8, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9]);
  return ticks.length ? ticks : [scaleMin, scaleMax];
}

function drawEquity(list) {
  const key = state.mode;
  const { data } = alignSeries(list, key);
  const money = key === 'balance';
  const fmt = money ? fmtMoney2 : (v) => v.toFixed(3) + '×';

  const opts = {
    width: $('#chart').clientWidth,
    height: 340,
    padding: [10, 8, 0, 0],
    cursor: { y: false, points: { size: 7 } },
    legend: { show: false },
    scales: {
      y: {
        distr: state.axis === 'log' ? 3 : 1,
        // uPlot's log default snaps the range to whole decades (10k -> 100k),
        // which wastes most of the plot. Hug the data instead.
        range: (u, lo, hi) => (state.axis === 'log' ? [lo * 0.94, hi * 1.06] : uPlot.rangeNum(lo, hi, 0.1, true)),
      },
    },
    axes: [
      { ...axisTheme() },
      {
        ...axisTheme(),
        size: 68,
        ...(state.axis === 'log'
          // uPlot's default log filter keeps only whole decades, which strips
          // 8 of our 9 ticks once the range spans more than one. We already
          // control the density in logSplits, so keep them all.
          ? { splits: logSplits, filter: (u, sp) => sp }
          : {}),
        // Filtered-out splits arrive here as null and must render as blank,
        // not as "$0".
        values: (u, ticks) => ticks.map((v) => {
          if (v == null) return null;
          if (!money) return v.toFixed(v < 10 ? 1 : 0) + '×';
          if (v >= 1e6) return '$' + (v / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M';
          if (v >= 1000) return '$' + Math.round(v / 1000) + 'k';
          return '$' + Math.round(v);
        }),
      },
    ],
    series: [
      { value: (u, v) => (v == null ? '' : new Date(v * 1000).toISOString().slice(0, 10)) },
      ...list.map((s) => ({
        label: s.name,
        stroke: s.color,
        width: 2,
        dash: s.dash,
        points: { show: false },
        spanGaps: false,
      })),
    ],
    plugins: [tooltipPlugin(list, fmt)],
  };

  if (uEquity) uEquity.destroy();
  uEquity = new uPlot(opts, data, $('#chart'));
}

function drawDrawdown(list) {
  const { data } = alignSeries(list, 'drawdown');
  // Overlapping translucent fills blend into a colour that belongs to neither
  // series, so an area is only honest when there is exactly one of them.
  const solo = list.length === 1;
  const opts = {
    width: $('#ddchart').clientWidth,
    height: 190,
    padding: [10, 8, 0, 0],
    cursor: { y: false, points: { size: 7 } },
    legend: { show: false },
    axes: [
      { ...axisTheme() },
      { ...axisTheme(), size: 68, values: (u, ticks) => ticks.map((v) => (v * 100).toFixed(0) + '%') },
    ],
    series: [
      {},
      ...list.map((s) => ({
        label: s.name,
        stroke: s.color,
        width: 2,
        dash: s.dash,
        fill: solo ? `color-mix(in srgb, ${s.color} 18%, transparent)` : null,
        points: { show: false },
        spanGaps: false,
      })),
    ],
    plugins: [tooltipPlugin(list, (v) => fmtPct(v, 1))],
  };
  if (uDraw) uDraw.destroy();
  uDraw = new uPlot(opts, data, $('#ddchart'));
}

/* Legend doubles as the readout: shows the final value, or the hovered one. */
function updateLegend(idx) {
  const list = seriesList();
  const host = $('#legend');
  const money = state.mode === 'balance';
  host.innerHTML = list.map((s, i) => {
    let v;
    if (idx != null && uEquity) v = uEquity.data[i + 1][idx];
    else v = s[state.mode][s[state.mode].length - 1];
    const txt = v == null ? '—' : money ? fmtMoney(v) : v.toFixed(2) + '×';
    return `<span class="item"><span class="swatch" style="background:${s.color}"></span>${s.name}<span class="val">${txt}</span></span>`;
  }).join('');
}

/* ------------------------------------------------------------------ table */
const ROWS = [
  { group: 'Outcome' },
  { label: 'Final balance', get: (s) => s.final_balance, fmt: fmtMoney, best: 'max' },
  { label: 'Total invested', get: (s) => s.contributed, fmt: fmtMoney, best: null },
  { label: 'Profit', get: (s) => s.profit, fmt: fmtMoney, best: 'max' },
  { group: 'Return' },
  { label: 'Total return', get: (s) => s.total_return, fmt: (v) => fmtPct(v, 1), best: 'max' },
  { label: 'CAGR', hint: 'time-weighted', get: (s) => s.cagr, fmt: (v) => fmtPct(v, 2), best: 'max' },
  { label: 'XIRR', hint: 'money-weighted', get: (s) => s.xirr, fmt: (v) => fmtPct(v, 2), best: 'max' },
  { group: 'Risk' },
  { label: 'Max drawdown', get: (s) => s.max_drawdown, fmt: (v) => fmtPct(v, 1), best: 'max' },
  { label: 'Volatility', hint: 'annualized', get: (s) => s.volatility, fmt: (v) => fmtPct(v, 1), best: 'min' },
  { label: 'Sharpe', get: (s) => s.sharpe, fmt: (v) => fmtNum(v, 2), best: 'max' },
  { label: 'Sortino', get: (s) => s.sortino, fmt: (v) => fmtNum(v, 2), best: 'max' },
  { label: 'Longest underwater', get: (s) => s.longest_underwater_days, fmt: (v) => (v == null ? '—' : (v / 365.25).toFixed(1) + ' yrs'), best: 'min' },
  { label: 'Beta vs benchmark', get: (s) => s.beta, fmt: (v) => fmtNum(v, 2), best: null },
  { label: 'Correlation', get: (s) => s.correlation, fmt: (v) => fmtNum(v, 2), best: null },
  { group: 'Detail' },
  { label: 'Best year', get: (s) => (s.best_year ? s.best_year.return : null), fmt: (v) => fmtPct(v, 1), best: 'max',
    extra: (s) => (s.best_year ? ` <span class="hint">${s.best_year.year}</span>` : '') },
  { label: 'Worst year', get: (s) => (s.worst_year ? s.worst_year.return : null), fmt: (v) => fmtPct(v, 1), best: 'max',
    extra: (s) => (s.worst_year ? ` <span class="hint">${s.worst_year.year}</span>` : '') },
  { label: 'Deepest decline', get: null, text: (s) => (s.drawdown_peak ? `${fmtDate(s.drawdown_peak)} → ${fmtDate(s.drawdown_trough)}` : '—') },
  { label: 'Recovered', get: null, text: (s) => (s.drawdown_recovered ? fmtDate(s.drawdown_recovered) : 'not yet') },
  { label: 'Withdrawn', get: (s) => s.withdrawn, fmt: fmtMoney, best: null, skipIfAllNull: true },
  { label: 'Withdrawal / yr', hint: 'at the start', get: (s) => s.withdrawal_per_year,
    fmt: fmtMoney, best: null, skipIfAllNull: true },
  { label: 'Money lasted', get: null, skipUnless: (s) => s.withdrawal_rate != null,
    text: (s) => (s.survived ? 'the whole period' : `ran out ${fmtDate(s.depleted_on)}`) },
  { label: 'Costs paid', get: (s) => s.costs_paid, fmt: fmtMoney2, best: 'min' },
  { label: 'Trades', get: (s) => s.trades, fmt: (v) => (v == null ? '—' : v.toLocaleString()), best: null },
];

function renderTable(list) {
  const t = $('#metrics');
  const head = `<thead><tr><th>Metric</th>${list.map((s) =>
    `<th><span class="dot" style="background:${s.color}"></span>${s.name}</th>`).join('')}</tr></thead>`;

  const body = ROWS.map((row) => {
    if (row.group) return `<tr class="group"><td colspan="${list.length + 1}">${row.group}</td></tr>`;
    // Withdrawal rows only make sense when something is being withdrawn.
    if (row.skipIfAllNull && list.every((s) => row.get(s.stats) == null)) return '';
    if (row.skipUnless && !list.some((s) => row.skipUnless(s.stats))) return '';

    let bestIdx = -1;
    if (row.best && row.get) {
      const vals = list.map((s) => row.get(s.stats));
      const valid = vals.map((v, i) => [v, i]).filter(([v]) => v != null && isFinite(v));
      if (valid.length > 1) {
        bestIdx = valid.reduce((a, b) => (row.best === 'max' ? (b[0] > a[0] ? b : a) : (b[0] < a[0] ? b : a)))[1];
      }
    }
    const cells = list.map((s, i) => {
      if (!row.get) {
        if (row.skipUnless && !row.skipUnless(s.stats)) return '<td>—</td>';
        return `<td>${row.text(s.stats)}</td>`;
      }
      const v = row.get(s.stats);
      const extra = row.extra ? row.extra(s.stats) : '';
      return `<td class="${i === bestIdx ? 'best' : ''}">${row.fmt(v)}${extra}</td>`;
    }).join('');
    const hint = row.hint ? ` <span class="hint">${row.hint}</span>` : '';
    return `<tr><td>${row.label}${hint}</td>${cells}</tr>`;
  }).join('');

  t.innerHTML = head + `<tbody>${body}</tbody>`;
}

/* -------------------------------------------------------------- projection */
let uProj = null;

function renderProjection(list) {
  const panel = $('#projection-panel');
  const withProj = list.filter((s) => s.projection);
  if (!withProj.length) {
    panel.hidden = true;
    if (uProj) { uProj.destroy(); uProj = null; }
    return;
  }
  panel.hidden = false;

  if (!withProj.some((s) => s.name === state.projFocus)) {
    state.projFocus = withProj[0].name;
  }
  $('#projection-focus').innerHTML = withProj.map((s) =>
    `<button type="button" data-name="${s.name}" class="${s.name === state.projFocus ? 'on' : ''}">${s.name}</button>`).join('');

  const p0 = withProj[0].projection;
  const drawing = withProj.some((s) => s.projection.prob_ran_out != null);

  // Table first -- the fan is the illustration, these are the numbers.
  const rows = [
    ['Best case (95th)', (p) => p.final.p95, 'money'],
    ['Good (75th)', (p) => p.final.p75, 'money'],
    ['Median', (p) => p.final.p50, 'money'],
    ['Poor (25th)', (p) => p.final.p25, 'money'],
    ['Worst case (5th)', (p) => p.final.p5, 'money'],
    ['Chance of ending below today', (p) => p.prob_below_start, 'pct'],
  ];
  if (drawing) {
    rows.push(['Chance of running out', (p) => p.prob_ran_out, 'pctbad']);
    rows.push(['If it runs out, typically after', (p) => p.median_years_to_depletion, 'years']);
  }

  $('#projection-table').innerHTML =
    `<thead><tr><th>In ${p0.years} years</th>${withProj.map((s) =>
      `<th><span class="dot" style="background:${s.color}"></span>${s.name}</th>`).join('')
    }</tr></thead><tbody>${
      rows.map(([label, get, kind]) => `<tr><td>${label}</td>${
        withProj.map((s) => {
          const v = get(s.projection);
          if (v == null) return '<td>—</td>';
          if (kind === 'money') return `<td>${fmtMoney(v)}</td>`;
          if (kind === 'years') return `<td>${v.toFixed(1)} yrs</td>`;
          const cls = kind === 'pctbad' && v > 0.05 ? ' class="bad"' : '';
          return `<td${cls}>${fmtPct(v, 1)}</td>`;
        }).join('')
      }</tr>`).join('')
    }</tbody>`;

  // Chart: a median line per portfolio, plus the 5th-95th band for the focused
  // one. Filling every band would blend into a colour belonging to no portfolio.
  const focus = withProj.find((s) => s.name === state.projFocus) || withProj[0];
  const stepToTs = (proj) => (n) =>
    Date.parse(proj.last_date + 'T00:00:00Z') / 1000 + n * (365.25 / 252) * 86400;

  const xs = p0.steps.map(stepToTs(p0));
  const iP5 = p0.percentiles.indexOf(5);
  const iP50 = p0.percentiles.indexOf(50);
  const iP95 = p0.percentiles.indexOf(95);

  const series = [{}];
  const data = [xs];
  data.push(focus.projection.bands.map((b) => b[iP95]));
  series.push({ label: '95th', stroke: focus.color, width: 1, dash: [3, 3],
                fill: `color-mix(in srgb, ${focus.color} 13%, transparent)`,
                points: { show: false } });
  data.push(focus.projection.bands.map((b) => b[iP5]));
  series.push({ label: '5th', stroke: focus.color, width: 1, dash: [3, 3],
                points: { show: false } });
  withProj.forEach((s) => {
    data.push(s.projection.bands.map((b) => b[iP50]));
    series.push({ label: s.name, stroke: s.color, width: 2, points: { show: false } });
  });

  const opts = {
    width: $('#projchart').clientWidth,
    height: 280,
    padding: [10, 8, 0, 0],
    cursor: { y: false, points: { size: 7 } },
    legend: { show: false },
    scales: { y: { distr: state.axis === 'log' ? 3 : 1,
                   range: (u, lo, hi) => (state.axis === 'log'
                     ? [Math.max(lo, 1) * 0.94, hi * 1.06]
                     : uPlot.rangeNum(lo, hi, 0.1, true)) } },
    axes: [
      { ...axisTheme() },
      { ...axisTheme(), size: 68,
        ...(state.axis === 'log'
          // uPlot's default log filter keeps only whole decades, which strips
          // 8 of our 9 ticks once the range spans more than one. We already
          // control the density in logSplits, so keep them all.
          ? { splits: logSplits, filter: (u, sp) => sp }
          : {}),
        values: (u, ticks) => ticks.map((v) => {
          if (v == null) return null;
          if (v >= 1e6) return '$' + (v / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M';
          if (v >= 1000) return '$' + Math.round(v / 1000) + 'k';
          return '$' + Math.round(v);
        }) },
    ],
    series,
  };
  if (uProj) uProj.destroy();
  uProj = new uPlot(opts, data, $('#projchart'));

  const terms = p0.real
    ? "in today's dollars, so these are amounts you could actually spend"
    : 'in future nominal dollars — switch on Real terms to see what they would buy';
  $('#projnote').textContent =
    `${p0.paths.toLocaleString()} simulated paths per portfolio, drawn in ` +
    `${p0.block_days}-day blocks to preserve the way slumps and recoveries ` +
    `actually unfold. Shaded band shows the 5th–95th percentile for ` +
    `${focus.name}. Figures are ${terms}.`;
}

/* --------------------------------------------------------- rolling returns */
let uRoll = null;

function availableWindows(list) {
  const counts = new Map();
  list.forEach((s) => (s.rolling || []).forEach((w) => {
    counts.set(w.years, (counts.get(w.years) || 0) + 1);
  }));
  // Only offer a window every series can actually fill, otherwise the chart
  // silently compares different holding periods.
  return [...counts.entries()].filter(([, n]) => n === list.length)
    .map(([y]) => y).sort((a, b) => a - b);
}

function renderRolling(list) {
  const windows = availableWindows(list);
  const panel = $('#rolling-panel');
  if (!windows.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  if (!windows.includes(state.rollingYears)) {
    // Prefer 10 years, else the longest the data supports.
    state.rollingYears = windows.includes(10) ? 10 : windows[windows.length - 1];
  }
  const yrs = state.rollingYears;

  $('#rolling-windows').innerHTML = windows.map((y) =>
    `<button type="button" data-years="${y}" class="${y === yrs ? 'on' : ''}">${y}Y</button>`).join('');

  const picked = list.map((s) => ({
    ...s, win: (s.rolling || []).find((w) => w.years === yrs),
  })).filter((s) => s.win);

  // Table first: it is the accessible reading of the same numbers, and the
  // headline ("worst 10-year stretch") is a table fact, not a chart fact.
  const rows = [
    ['Best', (w) => w.best, (v) => fmtPct(v, 1)],
    ['Median', (w) => w.median, (v) => fmtPct(v, 1)],
    ['Worst', (w) => w.worst, (v) => fmtPct(v, 1)],
    ['Periods that lost money', (w) => w.pct_negative, (v) => fmtPct(v, 1)],
    ['Number of periods', (w) => w.count, (v) => v.toLocaleString()],
  ];
  $('#rolling-table').innerHTML =
    `<thead><tr><th>Over any ${yrs} year${yrs > 1 ? 's' : ''}</th>${
      picked.map((s) => `<th><span class="dot" style="background:${s.color}"></span>${s.name}</th>`).join('')
    }</tr></thead><tbody>${
      rows.map(([label, get, fmt]) => `<tr><td>${label}</td>${
        picked.map((s) => {
          const v = get(s.win);
          const neg = typeof v === 'number' && v < 0 && label !== 'Periods that lost money';
          return `<td class="${neg ? 'neg' : ''}">${fmt(v)}</td>`;
        }).join('')
      }</tr>`).join('')
    }</tbody>`;

  // Chart: annualized return by the date you would have bought.
  const all = new Set();
  picked.forEach((s) => s.win.dates.forEach((d) => all.add(d)));
  const xdates = [...all].sort();
  const data = [xdates.map(toTs)].concat(picked.map((s) => {
    const m = new Map();
    s.win.dates.forEach((d, i) => m.set(d, s.win.values[i]));
    return xdates.map((d) => (m.has(d) ? m.get(d) : null));
  }));

  const opts = {
    width: $('#rollchart').clientWidth,
    height: 240,
    padding: [10, 8, 0, 0],
    cursor: { y: false, points: { size: 7 } },
    legend: { show: false },
    axes: [
      { ...axisTheme() },
      { ...axisTheme(), size: 68,
        values: (u, ticks) => ticks.map((v) => (v * 100).toFixed(0) + '%') },
    ],
    series: [
      {},
      ...picked.map((s) => ({
        label: s.name, stroke: s.color, width: 2, dash: s.dash,
        points: { show: false }, spanGaps: false,
      })),
    ],
    plugins: [rollTooltip(picked, yrs)],
  };
  if (uRoll) uRoll.destroy();
  uRoll = new uPlot(opts, data, $('#rollchart'));
}

function rollTooltip(list, yrs) {
  let tip;
  return {
    hooks: {
      init: (u) => {
        tip = document.createElement('div');
        tip.className = 'tip';
        tip.style.display = 'none';
        u.over.appendChild(tip);
      },
      setCursor: (u) => {
        const { idx, left, top } = u.cursor;
        if (idx == null || left < 0) { tip.style.display = 'none'; return; }
        const when = new Date(u.data[0][idx] * 1000).toISOString().slice(0, 10);
        const rows = list.map((s, i) => {
          const v = u.data[i + 1][idx];
          if (v == null) return '';
          return `<div class="row"><span class="nm"><span class="sw" style="background:${s.color}"></span>${s.name}</span><span class="vl">${fmtPct(v, 1)}</span></div>`;
        }).join('');
        tip.innerHTML = `<div class="when">Bought ${fmtDate(when)}, held ${yrs}y</div>${rows}`;
        tip.style.display = 'block';
        tip.style.left = Math.min(left + 14, u.over.clientWidth - tip.offsetWidth - 6) + 'px';
        tip.style.top = Math.max(top - 10, 4) + 'px';
      },
      setSize: () => { if (tip) tip.style.display = 'none'; },
    },
  };
}

/* ------------------------------------------------------ calendar year bars */
function renderYears(list) {
  const host = $('#years');
  const years = [...new Set(list.flatMap((s) => s.calendar_years.map((y) => y.year)))].sort();
  if (!years.length) { host.innerHTML = ''; return; }

  const n = list.length;
  const barW = Math.max(5, Math.min(16, 300 / (years.length * n / 4)));
  const gap = 2;                       // surface gap between adjacent bars
  const groupW = n * barW + (n - 1) * gap;
  const groupGap = Math.max(10, barW);
  const W = years.length * (groupW + groupGap) + 60;
  const H = 240, top = 12, bottom = 26;
  const plotH = H - top - bottom;

  const vals = list.flatMap((s) => s.calendar_years.map((y) => y.return));
  const lim = Math.max(0.05, Math.max(...vals.map(Math.abs))) * 1.08;
  const yFor = (v) => top + plotH / 2 - (v / lim) * (plotH / 2);
  const zero = top + plotH / 2;

  const parts = [];
  // Recessive gridlines on round percentages -- fractions of the data max give
  // labels like "-17%", which nobody reads as a reference line.
  const step = [0.05, 0.1, 0.2, 0.25, 0.5].find((c) => lim / c <= 4) || 1;
  for (let v = step; v <= lim; v += step) {
    [v, -v].forEach((sv) => {
      const y = yFor(sv);
      parts.push(`<line class="gl" x1="46" y1="${y.toFixed(1)}" x2="${W - 8}" y2="${y.toFixed(1)}"/>`);
      parts.push(`<text class="yr-label" x="40" y="${(y + 3).toFixed(1)}" text-anchor="end">${(sv * 100).toFixed(0)}%</text>`);
    });
  }

  years.forEach((yr, gi) => {
    const gx = 52 + gi * (groupW + groupGap);
    list.forEach((s, si) => {
      const rec = s.calendar_years.find((y) => y.year === yr);
      if (!rec) return;
      const x = gx + si * (barW + gap);
      const y0 = yFor(0), y1 = yFor(rec.return);
      const h = Math.max(1.5, Math.abs(y1 - y0));
      const up = rec.return >= 0;
      const r = Math.min(4, barW / 2, h);   // 4px rounded data-end
      // Rounded on the data end only; square where it meets the baseline.
      const d = up
        ? `M${x},${y0} v${-(h - r)} q0,${-r} ${r},${-r} h${barW - 2 * r} q${r},0 ${r},${r} v${h - r} z`
        : `M${x},${y0} v${h - r} q0,${r} ${r},${r} h${barW - 2 * r} q${r},0 ${r},${-r} v${-(h - r)} z`;
      parts.push(`<path d="${d}" fill="${s.color}" opacity="${rec.partial ? 0.45 : 1}">
        <title>${s.name} — ${yr}: ${fmtPct(rec.return, 1)}${rec.partial ? ' (partial year)' : ''}</title></path>`);
    });
    if (years.length <= 26 || gi % 2 === 0) {
      parts.push(`<text class="yr-label" x="${(gx + groupW / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle">${String(yr).slice(2)}</text>`);
    }
  });

  parts.push(`<line class="zero" x1="46" y1="${zero}" x2="${W - 8}" y2="${zero}"/>`);
  host.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="Return by calendar year">${parts.join('')}</svg>`;
}

/* ----------------------------------------------------------------- render */
function renderResults() {
  const list = seriesList();
  $('#empty').hidden = true;
  $('#output').hidden = false;

  const p0 = list[0];
  const real = p0.stats.real;
  $('#growth-sub').textContent =
    `${fmtDate(p0.dates[0])} to ${fmtDate(p0.dates[p0.dates.length - 1])} · ` +
    `${p0.stats.years.toFixed(1)} years · starting ${fmtMoney(state.result.settings.initial)}` +
    (real ? ` · real terms, in ${p0.dates[0].slice(0, 4)} dollars` : ' · nominal') +
    (state.mode === 'index' ? ' · deposits excluded' : '');

  drawEquity(list);
  drawDrawdown(list);
  requestAnimationFrame(refit);
  updateLegend(null);
  renderTable(list);
  renderProjection(list);
  renderRolling(list);
  renderYears(list);
}


/* Watch the containers, not the window: uPlot needs an explicit pixel width, and
   the panel can change size without the window doing so (sidebar wrap, zoom,
   scrollbar appearing). */
const refit = debounce(() => {
  if (!state.result) return;
  const w1 = $('#chart').clientWidth, w2 = $('#ddchart').clientWidth;
  if (uEquity && w1 > 0 && Math.abs(uEquity.width - w1) > 1) uEquity.setSize({ width: w1, height: 340 });
  if (uDraw && w2 > 0 && Math.abs(uDraw.width - w2) > 1) uDraw.setSize({ width: w2, height: 190 });
  const w3 = $('#rollchart').clientWidth;
  if (uRoll && w3 > 0 && Math.abs(uRoll.width - w3) > 1) uRoll.setSize({ width: w3, height: 240 });
  const w4 = $('#projchart').clientWidth;
  if (uProj && w4 > 0 && Math.abs(uProj.width - w4) > 1) uProj.setSize({ width: w4, height: 280 });
}, 100);

const ro = new ResizeObserver(refit);
window.addEventListener('resize', refit);

/* Series colours are read from CSS custom properties and painted into a canvas,
   so a theme change after render would otherwise leave stale colours behind. */
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (state.result) renderResults();
});

/* ------------------------------------------------------------------- init */
/* Light up the horizon chip that matches the current date range, if any. */
function syncHorizonChips() {
  const start = $('#start').value;
  const end = $('#end').value;
  [...$('#horizons').children].forEach((b) => {
    const y = b.dataset.years;
    let match;
    if (y === 'max') {
      match = !start;
    } else if (!start || !end) {
      match = false;
    } else {
      const d = new Date(end);
      d.setFullYear(d.getFullYear() - Number(y));
      match = d.toISOString().slice(0, 10) === start;
    }
    b.classList.toggle('on', match);
  });
}

function setHorizon(years) {
  const end = new Date();
  $('#end').value = end.toISOString().slice(0, 10);
  if (years === 'max') { $('#start').value = ''; return; }
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - Number(years));
  $('#start').value = start.toISOString().slice(0, 10);
}

async function init() {
  setHorizon(10);

  $('#horizons').onclick = (e) => {
    if (e.target.tagName !== 'BUTTON') return;
    [...e.currentTarget.children].forEach((b) => b.classList.remove('on'));
    e.target.classList.add('on');
    setHorizon(e.target.dataset.years);
  };
  [$('#start'), $('#end')].forEach((el) => {
    el.onchange = syncHorizonChips;
  });

  // Any global control going out of sync with the drawn chart should say so.
  ['#initial', '#benchmark', '#start', '#end', '#project',
   '#commission', '#slippage', '#expense', '#rf'].forEach((sel) => {
    $(sel).addEventListener('input', () => { updateStale(); save(); });
    $(sel).addEventListener('change', () => { updateStale(); save(); });
  });
  $('#horizons').addEventListener('click', () => setTimeout(updateStale, 0));

  $('#scale').onclick = (e) => {
    if (e.target.tagName !== 'BUTTON') return;
    const group = e.target.dataset.mode ? 'mode' : 'axis';
    [...e.currentTarget.children]
      .filter((b) => (group === 'mode' ? b.dataset.mode : b.dataset.axis))
      .forEach((b) => b.classList.remove('on'));
    e.target.classList.add('on');
    state[group] = e.target.dataset[group];
    if (state.result) renderResults();
  };

  ro.observe($('#chart'));
  ro.observe($('#ddchart'));
  ro.observe($('#rollchart'));
  ro.observe($('#projchart'));

  $('#real').onchange = () => { updateStale(); save(); };
  $('#refresh').onclick = refreshPrices;

  $('#projection-focus').onclick = (e) => {
    if (e.target.tagName !== 'BUTTON') return;
    state.projFocus = e.target.dataset.name;
    if (state.result) renderProjection(seriesList());
  };

  $('#rolling-windows').onclick = (e) => {
    if (e.target.tagName !== 'BUTTON') return;
    state.rollingYears = Number(e.target.dataset.years);
    save();
    if (state.result) renderRolling(seriesList());
  };

  $('#copylink').onclick = async () => {
    const url = location.origin + location.pathname + '#s=' + encodeState(snapshot());
    history.replaceState(null, '', url);
    try {
      await navigator.clipboard.writeText(url);
      const b = $('#copylink');
      b.textContent = 'Copied';
      setTimeout(() => { b.textContent = 'Copy link'; }, 1500);
    } catch (_) {
      message('warn', 'Could not copy automatically — the link is in your address bar.');
    }
  };

  $('#reset').onclick = () => {
    try { localStorage.removeItem(STORE_KEY); } catch (_) {}
    history.replaceState(null, '', location.pathname);
    location.reload();
  };

  $('#add').onclick = () => {
    if (state.portfolios.length >= MAX_PORTFOLIOS) return;
    state.portfolios.unshift(makePortfolio());
    renderCards();
    $('.rail').scrollTop = 0;
    $('#cards .card .sym').focus();
  };
  $('#run').onclick = run;

  // presets
  const presets = await (await fetch('/api/presets')).json();
  $('#presets').innerHTML = presets.map((p, i) =>
    `<button type="button" class="preset" data-i="${i}"><strong>${p.name}</strong><span>${p.blurb}</span></button>`).join('');
  $('#presets').onclick = (e) => {
    const btn = e.target.closest('.preset');
    if (!btn || state.portfolios.length >= MAX_PORTFOLIOS) return;
    state.portfolios.unshift(makePortfolio(presets[+btn.dataset.i]));
    renderCards();
    $('.rail').scrollTop = 0;
  };

  loadStatus();

  // Restore whatever was last open (or a shared link); otherwise seed a
  // comparison so the first run is one click.
  if (!loadSaved()) {
    // Pushed one at a time: nextFreeSlot() reads the live list.
    state.portfolios.push(makePortfolio(presets[0]));
    state.portfolios.push(makePortfolio(presets[1]));
  }
  [...$('#scale').children].forEach((b) => {
    const k = b.dataset.mode ? 'mode' : 'axis';
    b.classList.toggle('on', b.dataset[k] === state[k]);
  });
  renderCards();
  run();

  // Keep the rail's own scroll area sized to whatever the header currently is
  // -- it grows when the costs panel is opened.
  const topbar = $('.topbar');
  const fitRail = () => document.documentElement.style.setProperty(
    '--topbar-h', topbar.offsetHeight + 'px');
  new ResizeObserver(fitRail).observe(topbar);
  fitRail();
}

init();
