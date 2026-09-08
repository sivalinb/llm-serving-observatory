(function () {
  'use strict';
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  function display(value, unit = '', digits = 2) {
    return finite(value) ? `${value.toLocaleString(undefined, {maximumFractionDigits: digits})}${unit ? ' ' + unit : ''}` : 'Unknown';
  }
  function metricValue(series, name, labels = {}) {
    const rows = (series || []).filter(r => r.name === name && Object.entries(labels).every(([k, v]) => r.labels[k] === v));
    return rows.length && rows.every(r => finite(r.value)) ? rows.reduce((s, r) => s + r.value, 0) : null;
  }
  function timelineParts(record) {
    const ttft = record.ttft_ms, duration = record.duration_ms;
    if (!finite(ttft) || !finite(duration) || ttft < 0 || duration <= 0 || ttft > duration) return null;
    return {first: ttft, streaming: duration - ttft, firstPercent: 100 * ttft / duration};
  }
  function chartGeometry(series, width) {
    width = Math.max(220, width);
    const points = series.flatMap(s => s.points).filter(p => finite(p[0]) && finite(p[1]));
    if (!points.length) return null;
    const x0 = Math.min(...points.map(p => p[0])), x1 = Math.max(...points.map(p => p[0]));
    const lo = Math.min(0, ...points.map(p => p[1])), hi = Math.max(...points.map(p => p[1]));
    const y1 = hi === lo ? lo + 1 : hi + (hi - lo) * .08;
    return {width, x0, x1, lo, hi: y1,
      x: v => 72 + (v - x0) / (x1 - x0 || 1) * (width - 94),
      y: v => 213 - (v - lo) / (y1 - lo) * 188};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {finite, display, metricValue, timelineParts, chartGeometry};
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  const state = {key: '', operator: false, tab: 'requests', epoch: 0, controller: null,
    timer: null, busy: false, catalog: [], catalogPage: 0, selectedMetric: '', chart: null,
    records: [], requestOffset: 0, nextOffset: null, eventBefore: null, nextBefore: null};
  const colors = ['#076e5a', '#2777a4', '#895213', '#8251a1', '#a42a37', '#387966', '#766327', '#596fa8'];
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function empty(id, message) { $(id).replaceChildren(node('p', message, 'empty')); }
  function badge(text, severity = '') { return node('span', text, 'badge ' + severity); }
  function datetime(value) {
    const date = new Date(typeof value === 'number' ? value * 1000 : value);
    return value == null || !Number.isFinite(date.getTime()) ? 'Unknown' : date.toLocaleString();
  }
  function notice(message, error = false) { $('notice').textContent = message; $('notice').className = 'notice' + (error ? ' error' : ''); }
  function resetViews() {
    ['summary-cards', 'targets', 'resource-cards', 'alerts', 'metric-list', 'chart', 'chart-legend',
      'chart-samples', 'requests-table', 'events-table', 'request-detail'].forEach(id => $(id).replaceChildren());
    ['overview-freshness', 'catalog-note', 'metric-name', 'metric-help', 'chart-state', 'identity-note'].forEach(id => { $(id).textContent = ''; });
    $('request-detail').hidden = true;
    state.catalog = []; state.records = []; state.chart = null; state.selectedMetric = '';
    state.catalogPage = 0; state.requestOffset = 0; state.eventBefore = null;
    state.nextOffset = state.nextBefore = null;
  }
  function stopWork() {
    state.epoch += 1; state.controller?.abort(); state.controller = null; state.busy = false;
    clearTimeout(state.timer);
  }
  function disconnect(message = 'Signed out. No key is stored in this browser.') {
    stopWork(); state.key = ''; state.operator = false; resetViews();
    $('workspace').hidden = true; $('login-panel').hidden = false; $('access-key').value = '';
    $('role-badge').textContent = 'Not connected'; $('login-message').textContent = message;
    ['request-scope', 'event-scope'].forEach(id => { $(id).value = 'mine'; });
    document.querySelectorAll('.operator-only').forEach(el => { el.hidden = true; });
  }
  async function api(path, signal) {
    const r = await fetch('/api/observability/' + path, {headers: {Authorization: 'Bearer ' + state.key}, cache: 'no-store', signal});
    if (r.status === 401 || r.status === 403) {
      const error = new Error(r.status === 401 ? 'Your key expired or was revoked. Reconnect to continue.' : 'Operator access is no longer available. Reconnect for your personal workspace.');
      error.auth = true; throw error;
    }
    if (!r.ok) throw new Error(r.status === 429 ? 'Dashboard request limit reached. Wait one minute.' : 'Data could not be loaded. Check the service and try again.');
    return r.json();
  }
  function freshness(packet) {
    if (!packet) return 'Unavailable';
    return `${packet.state} · ${packet.fetched_at ? 'fetched ' + datetime(packet.fetched_at) : 'no successful fetch'}`;
  }
  function stat(title, value, note) {
    const dl = node('dl', undefined, 'stat'); dl.append(node('dt', title), node('dd', value));
    if (note) dl.append(node('small', note)); return dl;
  }
  function overview(data) {
    $('overview-freshness').textContent = freshness(data.summary);
    const rows = data.summary.data?.series || [];
    const input = metricValue(rows, 'assistant_tokens_total', {kind: 'input'});
    const cached = metricValue(rows, 'assistant_tokens_total', {kind: 'cached_input'});
    const share = finite(input) && input > 0 && finite(cached) ? cached / input * 100 : null;
    $('summary-cards').replaceChildren(
      stat('Output tokens', display(metricValue(rows, 'assistant_tokens_total', {kind: 'output'}), '', 0), 'Gateway counter'),
      stat('Cached input share', display(share, '%'), 'Cached input ÷ input'),
      stat('Active answers', display(metricValue(rows, 'assistant_active_requests'), '', 0), 'Gateway in-flight count'),
      stat('Engine generation', display(metricValue(rows, 'llamacpp:predicted_tokens_seconds'), 'tokens/s'), 'Exporter-reported average')
    );
    const targets = data.targets.data?.targets || [];
    $('targets').replaceChildren(...['shared-assistant', 'shared-model'].map(job => {
      const t = targets.find(row => row.job === job), box = node('article', undefined, 'target');
      const age = t?.last_scrape ? (Date.now() - Date.parse(t.last_scrape)) / 1000 : null;
      const status = data.targets.state !== 'ready' ? data.targets.state : !t ? 'not discovered' : t.health !== 'up' ? 'down' : !finite(age) || age > 90 ? 'stale scrape' : 'up';
      box.append(badge(status, status === 'up' ? '' : 'warn'), node('strong', job), node('p', 'Last scrape: ' + datetime(t?.last_scrape))); return box;
    }));
    const resource = data.gateway_resources, good = resource.status === 'ok' && resource.sample_age_seconds <= 10;
    const process = good ? resource.process : {}, cgroup = good ? resource.cgroup_namespace_root : {};
    $('resource-cards').replaceChildren(
      stat('Gateway CPU', display(process.cpu_cores, 'cores'), 'Measured process usage'),
      stat('Gateway RSS', display(finite(process.rss_bytes) ? process.rss_bytes / 1024 ** 2 : null, 'MiB'), 'Process resident memory'),
      stat('Gateway memory', display(finite(cgroup.memory_current_bytes) ? cgroup.memory_current_bytes / 1024 ** 2 : null, 'MiB'), 'Cgroup including charged pages'),
      stat('Gateway throttling', display(cgroup.cpu_throttled_seconds_total, 's'), 'Cumulative cgroup counter'),
      stat('Host available RAM', display(good && finite(resource.host?.memory_available_bytes) ? resource.host.memory_available_bytes / 1024 ** 3 : null, 'GiB'), 'Host-visible aggregate, not a container allocation')
    );
    $('alerts').replaceChildren(node('p', freshness(data.alerts), 'muted'));
    if (!data.alerts.data) $('alerts').append(node('p', 'Alert state unavailable. This does not mean there are no alerts.'));
    for (const rule of data.alerts.data?.rules || []) {
      const box = node('article', undefined, 'rule'), stateText = rule.healthy ? rule.state : 'evaluation unavailable';
      box.append(badge(stateText, stateText === 'inactive' ? '' : stateText === 'firing' ? 'error' : 'warn'), node('strong', rule.name), node('p', rule.description), node('p', 'Last evaluation: ' + datetime(rule.last_evaluation))); $('alerts').append(box);
    }
    const packets = [data.summary, data.targets, data.alerts];
    notice(packets.every(p => p.state === 'ready') ? 'Data fetched from private Prometheus. Check target scrape freshness below.' : 'Some telemetry is disabled, stale or unavailable. Missing data is not zero.', packets.some(p => p.state === 'unavailable'));
  }
  function catalogList() {
    const term = $('metric-search').value.toLowerCase();
    const found = state.catalog.filter(m => `${m.name} ${m.help} ${m.unit}`.toLowerCase().includes(term));
    const start = state.catalogPage * 12;
    $('catalog-note').textContent = `${found.length} matches · showing ${found.length ? start + 1 : 0}–${Math.min(start + 12, found.length)}. Missing historical families may no longer appear in the recent catalog.`;
    $('metric-list').replaceChildren(...found.slice(start, start + 12).map(m => {
      const button = node('button', m.name, 'metric-button' + (state.selectedMetric === m.name ? ' selected' : ''));
      button.type = 'button'; button.append(node('small', `${m.type} · ${m.unit || 'unit not declared'}`));
      button.addEventListener('click', () => { state.selectedMetric = m.name; refresh(); }); return button;
    }));
    $('catalog-prev').disabled = state.catalogPage === 0;
    $('catalog-next').disabled = start + 12 >= found.length;
  }
  function svg(tag, attrs, text) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    if (text !== undefined) el.textContent = text; return el;
  }
  function drawChart() {
    const data = state.chart;
    $('chart').replaceChildren(); $('chart-legend').replaceChildren(); $('chart-samples').replaceChildren();
    if (!data) return;
    const geometry = chartGeometry(data.series, $('chart').clientWidth);
    if (!geometry) { empty('chart', 'No finite samples in this window. The metric may be absent, idle, or not yet scraped.'); return; }
    const g = geometry, canvas = svg('svg', {viewBox: `0 0 ${g.width} 260`, role: 'img', 'aria-label': data.metric + ' over ' + data.window});
    canvas.append(svg('title', {}, data.metric), svg('desc', {}, 'Time-series chart. Recent numeric samples are available in the table below.'));
    for (let i = 0; i < 4; i++) {
      const value = g.lo + (g.hi - g.lo) * i / 3, y = g.y(value);
      canvas.append(svg('line', {x1: 72, x2: g.width - 22, y1: y, y2: y, stroke: '#d5e1dc'}));
      const label = Math.abs(value) >= 10000 ? value.toExponential(1) : display(value, '', 2);
      canvas.append(svg('text', {x: 64, y: y + 4, 'text-anchor': 'end'}, label));
    }
    const tickCount = g.width < 400 ? 2 : 3;
    for (let i = 0; i < tickCount; i++) {
      const value = g.x0 + (g.x1 - g.x0) * i / (tickCount - 1);
      canvas.append(svg('text', {x: g.x(value), y: 239, 'text-anchor': i === 0 ? 'start' : i === tickCount - 1 ? 'end' : 'middle'}, new Date(value * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})));
    }
    data.series.forEach((series, index) => {
      let segment = [];
      function flush() {
        if (segment.length > 1) canvas.append(svg('polyline', {points: segment.map(p => p.join(',')).join(' '), fill: 'none', stroke: colors[index], 'stroke-width': 2}));
        if (segment.length === 1) canvas.append(svg('circle', {cx: segment[0][0], cy: segment[0][1], r: 3, fill: colors[index]}));
        segment = [];
      }
      for (const p of series.points) { if (finite(p[0]) && finite(p[1])) segment.push([g.x(p[0]), g.y(p[1])]); else flush(); } flush();
      const label = Object.entries(series.labels).map(([k, v]) => `${k}=${v}`).join(' · ') || 'Calculated series';
      const legend = node('span', undefined); const line = node('i'); line.style.background = colors[index]; legend.append(line, document.createTextNode(label)); $('chart-legend').append(legend);
    });
    $('chart').append(canvas);
    const samples = data.series.flatMap((s, i) => s.points.slice(-5).map(p => [String(i + 1), datetime(p[0]), display(p[1])]));
    $('chart-samples').append(table(['Series', 'Time', 'Value (last 5 per series)'], samples));
  }
  function table(headings, rows) {
    const el = node('table'), head = node('thead'), tr = node('tr'), body = node('tbody');
    headings.forEach(h => { const th = node('th', h); th.scope = 'col'; tr.append(th); }); head.append(tr);
    rows.forEach(row => { const r = node('tr'); row.forEach(value => { const cell = node('td'); cell.append(value instanceof Node ? value : document.createTextNode(String(value))); r.append(cell); }); body.append(r); });
    el.append(head, body); return el;
  }
  function requestDetail(record) {
    const el = $('request-detail'); el.hidden = false; el.replaceChildren(node('h3', 'Request ' + record.id));
    const parts = timelineParts(record);
    if (parts) {
      const bar = node('div', undefined, 'timeline'); bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', `First content after ${display(parts.first, 'ms')}; streaming afterwards ${display(parts.streaming, 'ms')}`);
      const first = node('span'), rest = node('span'); first.style.width = parts.firstPercent + '%'; rest.style.width = (100 - parts.firstPercent) + '%'; bar.append(first, rest); el.append(bar);
      el.append(node('p', `First content: ${display(parts.first, 'ms')} · Streaming after first content: ${display(parts.streaming, 'ms')}`));
    } else el.append(node('p', 'A first-content timeline is unavailable for this request.'));
    el.append(node('p', 'TTFT includes retrieval and engine waiting/prefill. These are not separately measured engine spans. Browser network time is excluded.', 'muted'));
    const fields = [['Status', record.status], ['Created', datetime(record.created)], ['Total duration', display(record.duration_ms, 'ms')], ['Retrieval (inside TTFT)', display(record.retrieval_ms, 'ms')], ['Input tokens', display(record.tokens?.input, '', 0)], ['Output tokens', display(record.tokens?.output, '', 0)], ['Cached input subset', display(record.tokens?.cached_input, '', 0)], ['Uncached input', display(record.tokens?.uncached_input, '', 0)], ['Reasoning subset', display(record.tokens?.reasoning, '', 0)], ['Visible-output subset', display(record.tokens?.visible_output, '', 0)], ['Total tokens', display(record.tokens?.total, '', 0)], ['Initial reservation estimate', display(record.reserved_tokens_estimate, '', 0)], ['Finish reason', record.finish_reason || 'Unknown'], ['Citation IDs', record.citations || 'Unknown'], ['Trace ID (no stored trace backend)', record.trace_id || 'Unknown']];
    const facts = node('dl', undefined, 'facts'); fields.forEach(([k, v]) => facts.append(node('dt', k), node('dd', v))); el.append(facts);
    if (record.finish_reason === 'length' || record.citations !== 'present') el.append(node('p', 'Quality warning: the answer may be truncated or lack valid citation IDs. Transport success is not factual accuracy.', 'warning'));
    const related = node('button', 'Related events', 'secondary'); related.addEventListener('click', () => { $('event-request-id').value = record.id; $('event-scope').value = $('request-scope').value; state.eventBefore = null; selectTab('events'); }); el.append(related);
  }
  function renderRequests(data) {
    state.records = data.records; state.nextOffset = data.next_offset;
    $('request-detail').hidden = true; $('request-detail').replaceChildren();
    if (!data.records.length) empty('requests-table', 'No retained request metadata matches. Older records may be expired or deleted.');
    else $('requests-table').replaceChildren(table(['Request', 'Outcome', 'First content', 'Total time', 'Input / output', 'Created'], data.records.map(r => {
      const button = node('button', r.id.slice(0, 12) + '…'); button.setAttribute('aria-label', 'Inspect request ' + r.id); button.addEventListener('click', () => requestDetail(r));
      return [button, r.status, display(r.ttft_ms, 'ms'), display(r.duration_ms, 'ms'), `${display(r.tokens?.input, '', 0)} / ${display(r.tokens?.output, '', 0)}`, datetime(r.created)];
    })));
    $('requests-next').disabled = state.nextOffset === null; $('requests-latest').disabled = state.requestOffset === 0;
    notice('Retained request metadata loaded. No model call was made.');
  }
  function renderEvents(data) {
    state.nextBefore = data.next_before;
    if (!data.events.length) empty('events-table', 'No events match. Capture starts with this release; old request logs are not reconstructed.');
    else $('events-table').replaceChildren(table(['Time', 'Event', 'Code', 'Request', 'Duration'], data.events.map(e => [datetime(e.created), e.kind, e.code || '—', e.request_id || '—', display(e.duration_ms, 'ms')])));
    $('events-next').disabled = state.nextBefore === null; $('events-latest').disabled = state.eventBefore === null;
    notice('Sanitized application events loaded. This is not a full container-log or security-audit stream.');
  }
  function schedule() {
    clearTimeout(state.timer);
    if (state.key && $('auto-refresh').checked && !document.hidden) state.timer = setTimeout(refresh, 30000);
  }
  async function refresh() {
    if (!state.key || document.hidden) return;
    stopWork(); const epoch = state.epoch; state.controller = new AbortController(); state.busy = true;
    const signal = state.controller.signal;
    notice('Loading measured data…');
    try {
      if (state.tab === 'overview') { const data = await api('overview', signal); if (epoch === state.epoch) overview(data); }
      if (state.tab === 'metrics') {
        const result = await api('catalog', signal); if (epoch !== state.epoch) return;
        state.catalog = result.data?.metrics || []; catalogList();
        if (!state.catalog.length) { state.chart = null; drawChart(); $('chart-state').textContent = freshness(result); notice('Metric catalog unavailable. Check Prometheus configuration and connectivity.'); }
        else {
          if (!state.catalog.some(m => m.name === state.selectedMetric)) state.selectedMetric = state.catalog[0].name;
          catalogList(); const m = state.catalog.find(m => m.name === state.selectedMetric);
          state.chart = null; drawChart(); $('chart-state').textContent = 'Loading this measurement…';
          $('metric-name').textContent = m.name; $('metric-help').textContent = `${m.help} ${m.unit ? 'Unit: ' + m.unit + '.' : 'Unit not declared by exporter; inspect the metric definition.'}`;
          const result = await api('chart?' + new URLSearchParams({metric: m.name, window: $('chart-window').value}), signal); if (epoch !== state.epoch) return;
          state.chart = result.data?.series ? result.data : null; drawChart();
          $('chart-state').textContent = freshness(result) + (result.data?.truncated ? ' · First 8 series only' : '');
          notice('Read-only bounded metric query. Check Overview for target scrape freshness.');
        }
      }
      if (state.tab === 'requests') {
        const params = new URLSearchParams({scope: $('request-scope').value, offset: state.requestOffset, request_id: $('request-id').value});
        if ($('request-status').value) params.set('status', $('request-status').value);
        const data = await api('requests?' + params, signal); if (epoch === state.epoch) renderRequests(data);
      }
      if (state.tab === 'events') {
        const params = new URLSearchParams({scope: $('event-scope').value, request_id: $('event-request-id').value});
        if ($('event-kind').value) params.set('kind', $('event-kind').value);
        if (state.eventBefore !== null) params.set('before', state.eventBefore);
        const data = await api('events?' + params, signal); if (epoch === state.epoch) renderEvents(data);
      }
    } catch (error) {
      if (epoch !== state.epoch || error.name === 'AbortError') return;
      if (error.auth) disconnect(error.message); else notice(error.message + ' Any previously displayed data is stale.', true);
    } finally { if (epoch === state.epoch) { state.busy = false; schedule(); } }
  }
  function selectTab(tab) {
    if (['overview', 'metrics'].includes(tab) && !state.operator) return;
    state.tab = tab;
    ['overview', 'metrics', 'requests', 'events'].forEach(name => { $('panel-' + name).hidden = name !== tab; });
    document.querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-current', String(button.dataset.tab === tab)));
    refresh();
  }
  $('connect-form').addEventListener('submit', async event => {
    event.preventDefault(); stopWork(); resetViews(); state.key = $('access-key').value.trim(); $('access-key').value = '';
    const epoch = state.epoch; state.controller = new AbortController(); $('login-message').textContent = 'Checking access…';
    try {
      const data = await api('session', state.controller.signal); if (epoch !== state.epoch) return;
      state.operator = data.is_operator; $('role-badge').textContent = data.is_operator ? 'Operator · read-only' : 'Personal workspace';
      $('identity-note').textContent = 'User ' + data.user_id;
      document.querySelectorAll('.operator-only').forEach(el => { el.hidden = !data.is_operator; });
      $('login-panel').hidden = true; $('workspace').hidden = false;
      selectTab(data.is_operator ? 'overview' : 'requests');
    } catch (error) { if (epoch === state.epoch && error.name !== 'AbortError') disconnect(error.message); }
  });
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => selectTab(button.dataset.tab)));
  $('sign-out').addEventListener('click', () => disconnect());
  $('refresh').addEventListener('click', refresh); $('auto-refresh').addEventListener('change', schedule);
  $('metric-search').addEventListener('input', () => { state.catalogPage = 0; catalogList(); });
  $('catalog-prev').addEventListener('click', () => { state.catalogPage--; catalogList(); });
  $('catalog-next').addEventListener('click', () => { state.catalogPage++; catalogList(); });
  $('chart-window').addEventListener('change', refresh);
  $('request-filter').addEventListener('submit', e => { e.preventDefault(); state.requestOffset = 0; refresh(); });
  $('event-filter').addEventListener('submit', e => { e.preventDefault(); state.eventBefore = null; refresh(); });
  $('requests-next').addEventListener('click', () => { state.requestOffset = state.nextOffset; refresh(); });
  $('requests-latest').addEventListener('click', () => { state.requestOffset = 0; refresh(); });
  $('events-next').addEventListener('click', () => { state.eventBefore = state.nextBefore; refresh(); });
  $('events-latest').addEventListener('click', () => { state.eventBefore = null; refresh(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopWork(); else refresh(); });
  window.addEventListener('pagehide', () => disconnect());
  window.addEventListener('pageshow', event => { if (event.persisted) disconnect(); });
  new ResizeObserver(() => { if (state.tab === 'metrics') drawChart(); }).observe($('chart'));
})();
