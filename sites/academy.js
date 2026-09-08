/* Browser-only teaching models: no inference, network requests, analytics or persistence. */
((root) => {
  'use strict';
  const GiB = 2 ** 30;
  function number(value, min, max, integer = false) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) {
      throw new RangeError('Enter finite values within the displayed limits; counts must be whole numbers.');
    }
    return value;
  }
  function memoryBudget(p) {
    const parameters = number(p.parameters, .1, 200), weightBits = number(p.weightBits, 4, 32);
    const layers = number(p.layers, 1, 160, true), heads = number(p.heads, 1, 128, true);
    const dim = number(p.dim, 16, 512, true), kvBits = number(p.kvBits, 4, 16);
    const context = number(p.context, 1, 262144, true), sequences = number(p.sequences, 1, 256, true);
    const capacity = number(p.capacity, 1, 1024), reserve = number(p.reserve, 0, 256);
    const weights = parameters * 1e9 * weightBits / 8 / GiB;
    const kv = 2 * layers * heads * dim * context * sequences * (kvBits / 8) / GiB;
    const total = weights + kv + reserve;
    return {weights, kv, reserve, total, capacity, headroom: capacity - total, fits: total <= capacity};
  }
  function latencyBudget(p) {
    const input = number(p.input, 1, 131072, true), cache = number(p.cache, 0, 100);
    const rate = number(p.rate, 1, 1000000), queue = number(p.queue, 0, 60000);
    const size = number(p.size, 0, 131072), bandwidth = number(p.bandwidth, .1, 1000);
    const setup = number(p.setup, 0, 10000), first = number(p.first, 0, 10000);
    if (!['combined', 'disaggregated'].includes(p.mode)) throw new RangeError('Choose a serving mode.');
    const prefill = input * (1 - cache / 100) / rate * 1000;
    const transfer = p.mode === 'disaggregated' ? setup + size / 1024 / bandwidth * 1000 : 0;
    return {queue, prefill, transfer, first, total: queue + prefill + transfer + first};
  }
  function tokenLedger(p) {
    const input = number(p.input, 0, 1000000, true), output = number(p.output, 0, 1000000, true);
    const cached = p.cached === null ? null : number(p.cached, 0, input, true);
    const reasoning = p.reasoning === null ? null : number(p.reasoning, 0, output, true);
    return {input, output, cached, reasoning, total: input + output, remainingOutput: reasoning === null ? null : output - reasoning};
  }
  function percentile(values, q) {
    if (!values.length) return null;
    number(q, 0, 1);
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.max(0, Math.ceil(q * sorted.length) - 1)];
  }
  function simulateTraffic(p) {
    const interval = number(p.interval, 10, 2000), slots = number(p.slots, 1, 8, true);
    const maxQueue = number(p.maxQueue, 0, 64, true), ttftTarget = number(p.ttftTarget, 1, 10000);
    const tpotTarget = number(p.tpotTarget, 1, 1000), hourlyCost = number(p.hourlyCost, 0, 1000);
    const available = Array(slots).fill(0), requests = [];
    for (let i = 0; i < 24; i++) {
      const arrival = i * interval;
      const next = Math.min(...available), slot = available.indexOf(next);
      const queued = requests.filter(r => r.outcome !== 'rejected' && r.start > arrival).length;
      if (next > arrival && queued >= maxQueue) {
        requests.push({arrival, outcome: 'rejected'});
        continue;
      }
      const start = Math.max(arrival, next), ttft = start - arrival + 220, finish = start + 840;
      available[slot] = finish;
      requests.push({arrival, start, finish, ttft, tpot: 20, outcome: ttft <= ttftTarget && 20 <= tpotTarget ? 'good' : 'late'});
    }
    const accepted = requests.filter(r => r.outcome !== 'rejected'), good = accepted.filter(r => r.outcome === 'good').length;
    const duration = Math.max(...available, 23 * interval) / 1000;
    const cost = hourlyCost * duration / 3600;
    return {requests, accepted: accepted.length, rejected: 24 - accepted.length, good, duration,
      throughput: accepted.length / duration, goodput: good / duration, p95: percentile(accepted.map(r => r.ttft), .95),
      cost, costPerGood: good ? cost / good : null};
  }
  function matchesLesson(text, track, query, selectedTrack) {
    return (selectedTrack === 'all' || track === selectedTrack) && query.toLowerCase().trim().split(/\s+/).every(word => text.toLowerCase().includes(word));
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {memoryBudget, latencyBudget, tokenLedger, percentile, simulateTraffic, matchesLesson};
  if (!root.document) return;
  const doc = root.document, $ = id => doc.getElementById(id);
  if (!$('learning-controls')) return;
  const lessons = [...doc.querySelectorAll('.lesson')];
  const index = new Map(lessons.map(l => [l.id, l.textContent]));
  let selectedTrack = 'all';
  function filter() {
    let count = 0;
    for (const lesson of lessons) {
      lesson.hidden = !matchesLesson(index.get(lesson.id), lesson.dataset.track, $('lesson-search').value, selectedTrack);
      if (!lesson.hidden) count++;
    }
    for (const button of doc.querySelectorAll('[data-track-filter]')) button.setAttribute('aria-pressed', String(button.dataset.trackFilter === selectedTrack));
    $('lesson-count').textContent = `${count} of ${lessons.length} modules`;
    $('no-lessons').hidden = count !== 0;
  }
  function reset() { selectedTrack = 'all'; $('lesson-search').value = ''; filter(); }
  function reveal(hash) {
    const lesson = lessons.find(l => '#' + l.id === hash);
    if (lesson) { reset(); lesson.open = true; }
  }
  $('lesson-search').addEventListener('input', filter);
  $('clear-filters').addEventListener('click', reset);
  for (const button of doc.querySelectorAll('[data-track-filter]')) button.addEventListener('click', () => { selectedTrack = button.dataset.trackFilter; filter(); });
  for (const link of doc.querySelectorAll('a[href^="#"]')) link.addEventListener('click', () => reveal(link.getAttribute('href')));
  root.addEventListener('hashchange', () => reveal(root.location.hash));
  reveal(root.location.hash);
  // Quiz answers are intentionally public learning material, not a certification exam.
  for (const quiz of doc.querySelectorAll('.quiz')) {
    const button = quiz.querySelector('.check-answer'), result = quiz.querySelector('.quiz-result');
    button.hidden = false;
    quiz.addEventListener('change', () => { result.textContent = ''; delete result.dataset.correct; });
    button.addEventListener('click', () => {
      const selected = quiz.querySelector('input:checked');
      if (!selected) { result.textContent = 'Choose an answer first.'; return; }
      const correct = selected.value === quiz.dataset.answer;
      result.dataset.correct = String(correct);
      result.textContent = correct ? 'Correct. Open the explanation to review why.' : 'Not quite. Review the explanation and try again.';
      quiz.querySelector('.answer-key').open = true;
    });
  }
  function read(id, nullable = false) {
    const input = $(id);
    input.removeAttribute('aria-invalid');
    if (nullable && input.value.trim() === '') return null;
    if (input.value.trim() === '' || !input.checkValidity()) {
      input.setAttribute('aria-invalid', 'true');
      throw new RangeError('Enter valid values within the displayed limits. Only token subsets may be blank.');
    }
    return Number(input.value);
  }
  const fixed = (n, places = 2) => n.toLocaleString('en-US', {maximumFractionDigits: places, minimumFractionDigits: places});
  function bind(id, resultId, calculate, show, clear) {
    const update = () => {
      try { show(calculate()); }
      catch (error) { $(resultId).textContent = error instanceof RangeError ? error.message : 'This exercise could not be calculated.'; clear?.(); }
    };
    $(id).addEventListener('input', update);
    $(id).addEventListener('change', update);
    update();
  }
  bind('memory-exercise', 'memory-result', () => memoryBudget({parameters:read('mem-params'), weightBits:read('mem-weight'), layers:read('mem-layers'), heads:read('mem-heads'), dim:read('mem-dim'), kvBits:read('mem-kv'), context:read('mem-context'), sequences:read('mem-sequences'), capacity:read('mem-capacity'), reserve:read('mem-reserve')}), r => {
    $('memory-result').textContent = `Weights ${fixed(r.weights)} GiB + KV ${fixed(r.kv)} GiB + reserve ${fixed(r.reserve)} GiB\nTotal ${fixed(r.total)} / ${fixed(r.capacity)} GiB\n${r.fits ? 'Fits this simplified budget' : 'Exceeds capacity'} · ${fixed(Math.abs(r.headroom))} GiB ${r.fits ? 'headroom' : 'over budget'}`;
    $('memory-fill').style.width = `${Math.min(100, r.total / r.capacity * 100)}%`;
    $('memory-fill').style.background = r.fits ? '#97e2b0' : '#e8aa83';
  }, () => { $('memory-fill').style.width = '0%'; });
  bind('latency-exercise', 'latency-result', () => latencyBudget({input:read('lat-input'), cache:read('lat-cache'), rate:read('lat-rate'), queue:read('lat-queue'), mode:$('lat-mode').value, size:read('lat-size'), bandwidth:read('lat-bandwidth'), setup:read('lat-setup'), first:read('lat-first')}), r => {
    $('latency-result').textContent = `Queue ${fixed(r.queue)} ms\nPrompt work ${fixed(r.prefill)} ms\nKV handoff ${fixed(r.transfer)} ms\nFirst output ${fixed(r.first)} ms\nIllustrated TTFT ${fixed(r.total)} ms`;
    $('latency-bars').replaceChildren(...[r.queue,r.prefill,r.transfer,r.first].map(v => { const bar = doc.createElement('span'); bar.style.width = `${r.total ? v / r.total * 100 : 0}%`; return bar; }));
  }, () => $('latency-bars').replaceChildren());
  bind('token-exercise', 'token-result', () => tokenLedger({input:read('tok-input'), cached:read('tok-cache', true), output:read('tok-output'), reasoning:read('tok-reason', true)}), r => {
    $('token-result').textContent = `Total ${r.total.toLocaleString('en-US')} tokens\nCached input ${r.cached ?? 'unknown'} (subset)\nReasoning ${r.reasoning ?? 'unknown'} (subset)\nRemaining output ${r.remainingOutput ?? 'unknown'} tokens`;
  });
  bind('traffic-exercise', 'traffic-result', () => simulateTraffic({interval:read('traffic-interval'), slots:read('traffic-slots'), maxQueue:read('traffic-queue'), ttftTarget:read('traffic-ttft'), tpotTarget:read('traffic-tpot'), hourlyCost:read('traffic-cost')}), r => {
    $('traffic-result').textContent = `${r.accepted}/24 accepted · ${r.rejected} rejected\n${r.good} meet both targets · ${r.accepted-r.good} miss a target\nAccepted p95 TTFT ${fixed(r.p95,0)} ms\nThroughput ${fixed(r.throughput)} requests/s\nGoodput ${fixed(r.goodput)} requests/s\nRun ${fixed(r.duration)} s · cost $${fixed(r.cost,6)}\nCost / SLO completion ${r.costPerGood === null ? 'not defined: none qualified' : '$'+fixed(r.costPerGood,6)}\nGreen = within targets · amber = late · red = rejected`;
    $('traffic-dots').replaceChildren(...r.requests.map(r => { const dot=doc.createElement('span');dot.dataset.outcome=r.outcome;return dot; }));
  }, () => $('traffic-dots').replaceChildren());
  $('learning-controls').hidden = false;
  $('exercise-controls').hidden = false;
  filter();
})(typeof window === 'undefined' ? globalThis : window);
