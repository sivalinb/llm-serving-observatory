/* Pure teaching state; no telemetry, storage, credentials or cloud calls. */
(function(root) {
  'use strict';
  const journeys = ['recover', 'detect', 'trace', 'reproduce'];
  function createFlow({change = () => {}, schedule = setTimeout, cancel = clearTimeout, reduced = false} = {}) {
    let journey = 'recover', step = 0, playing = false, timer = null;
    const snapshot = () => ({journey, step, playing});
    const clear = () => { if (timer !== null) cancel(timer); timer = null; };
    const emit = () => change(snapshot());
    const pause = () => {clear(); playing = false; emit();};
    const tick = () => {timer = null; step++; if (step === 4) playing = false; emit(); if (playing) timer = schedule(tick, 9000);};
    return {snapshot, pause,
      select(value) {if (!journeys.includes(value)) throw new RangeError('Unknown journey'); pause(); journey = value; step = 0; emit();},
      move(delta) {if (![1,-1].includes(delta)) throw new RangeError('Invalid step'); pause(); step = Math.max(0, Math.min(4, step + delta)); emit();},
      play() {if (playing || reduced) return; if (step === 4) step = 0; playing = true; emit(); timer = schedule(tick, 9000);},
      motion(value) {reduced = Boolean(value); if (reduced) pause();},
      destroy: pause
    };
  }
  if (typeof module !== 'undefined') module.exports = {createFlow};
  if (!root.document) return;
  const doc = root.document, controls = doc.getElementById('flow-controls');
  if (!controls) return;
  const motion = root.matchMedia('(prefers-reduced-motion: reduce)');
  const previous = doc.getElementById('flow-previous'), next = doc.getElementById('flow-next'), play = doc.getElementById('flow-play');
  const caption = doc.getElementById('flow-caption');
  const buttons = [...controls.querySelectorAll('[data-journey]')];
  const flow = createFlow({reduced: motion.matches, change(state) {
    doc.body.dataset.journey = state.journey;
    doc.body.classList.toggle('flow-playing', state.playing);
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.journey === state.journey)));
    const steps = [...doc.querySelectorAll('.journeys .' + state.journey + ' li')];
    doc.querySelectorAll('.journeys li').forEach(item => item.classList.remove('current-step'));
    steps[state.step].classList.add('current-step');
    caption.textContent = state.journey.toUpperCase() + ' / ' + (state.step + 1) + ' OF 5 — ' + steps[state.step].textContent;
    previous.disabled = state.step === 0; next.disabled = state.step === 4;
    play.textContent = state.playing ? 'Pause journey' : 'Play this journey';
    play.disabled = motion.matches;
    play.title = motion.matches ? 'Reduced motion enabled. Use Previous and Next.' : '';
  }});
  buttons.forEach(button => button.addEventListener('click', () => flow.select(button.dataset.journey)));
  previous.addEventListener('click', () => flow.move(-1)); next.addEventListener('click', () => flow.move(1));
  play.addEventListener('click', () => flow.snapshot().playing ? flow.pause() : flow.play());
  doc.addEventListener('visibilitychange', () => {if (doc.hidden) flow.pause();});
  root.addEventListener('pagehide', flow.pause);
  motion.addEventListener('change', event => {flow.motion(event.matches); flow.pause();});
  flow.select('recover'); controls.hidden = false;
})(typeof window === 'undefined' ? globalThis : window);
