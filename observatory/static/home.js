/* An explanatory state machine. It never calls an inference endpoint or invents live metrics. */
((root) => {
  'use strict';
  const phases = {
    request: {title: 'A question arrives.', description: 'The gateway checks access, finds relevant documentation and admits work only when quota and capacity are available.'},
    prefill: {title: 'Read once. Build useful memory.', description: 'Prefill processes the input prompt and creates attention keys and values in the KV cache. More input usually means more work before an answer can begin.'},
    transfer: {title: 'Move the cache, not just the question.', description: 'With separate prefill and decode workers, KV state must reach the decode worker. Network bandwidth, state size and handoff latency now matter. This is conceptual here; the lab models that transfer.'},
    first: {title: 'The first visible output arrives.', description: 'This is the TTFT milestone: time to first token or visible content. Waiting, preparation and the first generation step happen before it. A stream chunk can contain more than one token.'},
    decode: {title: 'Keep generating. Keep reusing.', description: 'Decode generates successive tokens using the growing KV cache. The server streams text as it becomes available. Chunk gaps are not necessarily individual token latencies.'},
    observe: {title: 'Turn the journey into evidence.', description: 'The real service records timing and reported input/output usage. Metrics show patterns; traces connect stages. Unknown counts stay unknown. This tour makes no model calls or performance measurements.'}
  };
  const paths = {
    combined: ['request', 'prefill', 'first', 'decode', 'observe'],
    disaggregated: ['request', 'prefill', 'transfer', 'first', 'decode', 'observe']
  };
  const output = ['Longer', 'prompts', 'need', 'more', 'prefill', 'work.'];

  function createTour({onChange = () => {}, schedule = setTimeout, cancel = clearTimeout, reducedMotion = false} = {}) {
    let mode = 'combined', index = 0, playing = !reducedMotion, timer = null, destroyed = false;
    function snapshot() {
      const phase = paths[mode][index];
      return {mode, index, playing, phase, steps: [...paths[mode]], ...phases[phase],
        output: phase === 'first' ? output.slice(0, 1) : ['decode', 'observe'].includes(phase) ? [...output] : []};
    }
    function clear() { if (timer !== null) cancel(timer); timer = null; }
    function emit(announce = false) { if (!destroyed) onChange(snapshot(), announce); }
    function queue() {
      clear();
      if (playing && !destroyed) timer = schedule(() => {
        timer = null; index = (index + 1) % paths[mode].length; emit(); queue();
      }, 3000);
    }
    const api = {
      snapshot,
      play() { if (destroyed) return; playing = true; emit(true); queue(); },
      pause() { if (destroyed) return; playing = false; clear(); emit(true); },
      restart() { if (destroyed) return; index = 0; emit(true); queue(); },
      setMode(value) {
        if (destroyed) return;
        if (!Object.hasOwn(paths, value)) throw new RangeError('Unknown serving mode');
        mode = value; index = 0; emit(true); queue();
      },
      selectPhase(value) {
        if (destroyed) return;
        const next = paths[mode].indexOf(value);
        if (next < 0) throw new RangeError('Stage is not in this serving mode');
        index = next; playing = false; clear(); emit(true);
      },
      setReducedMotion(value) { if (value) api.pause(); },
      destroy() { playing = false; clear(); destroyed = true; }
    };
    emit(); queue();
    return api;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {createTour};
  if (!root.document) return;

  // Preserve old local lab bookmarks while giving the root route a real homepage.
  const legacy = ['lab', 'hardware', 'architecture', 'benchmarks', 'learn'];
  if (legacy.includes(root.location.hash.slice(1))) {
    root.location.replace('/lab' + root.location.hash);
    return;
  }
  const doc = root.document, $ = id => doc.getElementById(id), panel = $('tour');
  if (!panel) return;
  const preference = root.matchMedia('(prefers-reduced-motion: reduce)');
  const phaseButtons = [...doc.querySelectorAll('.step-rail button')];
  let renderedOutput = '';
  const tour = createTour({reducedMotion: preference.matches || doc.hidden, onChange(state, announce) {
    panel.dataset.phase = state.phase;
    panel.dataset.mode = state.mode;
    panel.dataset.playing = String(state.playing);
    $('tour-play').textContent = state.playing ? 'Pause tour' : 'Play tour';
    $('tour-play').setAttribute('aria-label', state.playing ? 'Pause request animation' : 'Play request animation');
    $('transfer-step').hidden = state.mode !== 'disaggregated';
    $('boundary-label').textContent = state.mode === 'combined' ? 'ONE MODEL PROCESS · SHARED CACHE' : 'SEPARATE PREFILL + DECODE WORKERS';
    $('cache-label').textContent = state.mode === 'combined' ? 'KV CACHE' : 'KV STATE';
    for (const button of doc.querySelectorAll('.mode-switch button')) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === state.mode));
    }
    for (const button of phaseButtons) {
      const position = state.steps.indexOf(button.dataset.phase);
      if (position >= 0) button.firstChild.textContent = String(position + 1).padStart(2, '0') + ' ';
      if (button.dataset.phase === state.phase) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    }
    $('stage-number').textContent = String(state.index + 1).padStart(2, '0');
    $('stage-title').textContent = state.title;
    $('stage-description').textContent = state.description;
    $('first-marker').hidden = !state.output.length;
    const value = state.output.join(' ');
    if (value !== renderedOutput || !$('tour-output').firstChild) {
      $('tour-output').replaceChildren();
      for (const piece of state.output) {
        const span = doc.createElement('span'); span.className = 'output-piece'; span.textContent = piece;
        $('tour-output').append(span);
      }
      if (!state.output.length) {
        const span = doc.createElement('span'); span.className = 'waiting'; span.textContent = 'Waiting for the model…';
        $('tour-output').append(span);
      }
      renderedOutput = value;
    }
    if (announce) $('tour-announcement').textContent = `${state.playing ? 'Playing' : 'Paused'}. ${state.title} ${state.description}`;
  }});
  $('tour-controls').hidden = false;
  $('tour-play').addEventListener('click', () => tour.snapshot().playing ? tour.pause() : tour.play());
  $('tour-restart').addEventListener('click', () => tour.restart());
  for (const button of doc.querySelectorAll('.mode-switch button')) {
    button.addEventListener('click', () => tour.setMode(button.dataset.mode));
  }
  for (const button of phaseButtons) button.addEventListener('click', () => tour.selectPhase(button.dataset.phase));
  preference.addEventListener('change', event => tour.setReducedMotion(event.matches));
  doc.addEventListener('visibilitychange', () => { if (doc.hidden) tour.pause(); });
  const observer = typeof root.IntersectionObserver === 'function' ? new root.IntersectionObserver(entries => {
    if (!entries[0].isIntersecting) tour.pause();
  }) : null;
  observer?.observe(panel);
  root.addEventListener('pagehide', () => { tour.pause(); });
  if (['localhost', '127.0.0.1', '[::1]'].includes(root.location.hostname)) $('local-lab-link').hidden = false;
})(typeof window === 'undefined' ? globalThis : window);
