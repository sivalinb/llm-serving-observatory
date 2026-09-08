(function () {
  'use strict';
  function createGuide({count = 7, reducedMotion = false, onChange = () => {}, schedule = setTimeout, cancel = clearTimeout} = {}) {
    if (!Number.isInteger(count) || count < 1) throw new RangeError('Invalid step count');
    let index = 0, playing = false, timer = null, destroyed = false;
    const snapshot = () => ({index, playing, reducedMotion, count});
    const clear = () => { if (timer !== null) cancel(timer); timer = null; };
    function render(announce = false) {
      clear(); if (destroyed) return;
      onChange(snapshot(), announce);
      if (playing) timer = schedule(() => {
        timer = null; if (destroyed || !playing) return;
        index = Math.min(count - 1, index + 1);
        if (index === count - 1) playing = false;
        render();
      }, 12000);
    }
    const api = {
      snapshot,
      select(value) {
        if (!Number.isInteger(value) || value < 0 || value >= count) throw new RangeError('Invalid step');
        if (destroyed) return;
        index = value; playing = false; render(true);
      },
      next() { api.select(Math.min(count - 1, index + 1)); },
      previous() { api.select(Math.max(0, index - 1)); },
      play() {
        if (destroyed || reducedMotion || count === 1) return;
        if (index === count - 1) index = 0;
        playing = true; render(true);
      },
      pause() { playing = false; render(true); },
      setReducedMotion(value) { reducedMotion = !!value; if (reducedMotion) playing = false; render(); },
      destroy() { clear(); playing = false; destroyed = true; }
    };
    render(); return api;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {createGuide};
  if (typeof document === 'undefined') return;
  const root = document.getElementById('system');
  if (!root?.classList.contains('usage-guide')) return;
  const panels = Array.from(root.querySelectorAll('[data-guide-panel]'));
  const steps = Array.from(root.querySelectorAll('[data-guide-step]'));
  if (panels.length !== 7 || steps.length !== 7) return; // Keep the readable no-script fallback.
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const play = document.getElementById('guide-play');
  const guide = createGuide({count: panels.length, reducedMotion: motion.matches, onChange(state, announce) {
    panels.forEach((panel, i) => { panel.hidden = i !== state.index; });
    steps.forEach((step, i) => { if (i === state.index) step.setAttribute('aria-current', 'step'); else step.removeAttribute('aria-current'); });
    root.classList.toggle('is-playing', state.playing);
    play.textContent = state.reducedMotion ? 'Reduced motion · use Next' : state.playing ? 'Pause walkthrough' : state.index === state.count - 1 ? 'Replay walkthrough' : 'Play walkthrough';
    play.disabled = state.reducedMotion;
    play.setAttribute('aria-pressed', String(state.playing));
    document.getElementById('guide-prev').disabled = state.index === 0;
    document.getElementById('guide-next').disabled = state.index === state.count - 1;
    const position = `Step ${state.index + 1} of ${state.count}`;
    document.getElementById('guide-position').textContent = position;
    if (announce) document.getElementById('guide-announcement').textContent = `${position}: ${panels[state.index].querySelector('h3').textContent}`;
  }});
  root.classList.add('is-enhanced');
  document.getElementById('guide-controls').hidden = false;
  function selectHash() {
    const index = panels.findIndex(panel => '#' + panel.id === window.location.hash);
    if (index >= 0) guide.select(index);
  }
  selectHash();
  steps.forEach((step, index) => {
    step.addEventListener('click', event => { event.preventDefault(); guide.select(index); });
    step.addEventListener('keydown', event => {
      const target = event.key === 'ArrowRight' ? Math.min(6, index + 1) : event.key === 'ArrowLeft' ? Math.max(0, index - 1) : event.key === 'Home' ? 0 : event.key === 'End' ? 6 : null;
      if (target !== null) { event.preventDefault(); guide.select(target); steps[target].focus(); }
    });
  });
  play.addEventListener('click', () => guide.snapshot().playing ? guide.pause() : guide.play());
  document.getElementById('guide-prev').addEventListener('click', () => guide.previous());
  document.getElementById('guide-next').addEventListener('click', () => guide.next());
  // Examples are handled by the existing assistant controller: fill only, never submit.
  root.querySelectorAll('[data-question], .guide-action').forEach(control => control.addEventListener('click', () => guide.pause()));
  const visibility = () => { if (document.hidden) guide.pause(); };
  const motionChange = event => guide.setReducedMotion(event.matches);
  document.addEventListener('visibilitychange', visibility);
  window.addEventListener('hashchange', selectHash);
  motion.addEventListener('change', motionChange);
  const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries => {
    if (!entries[0].isIntersecting) guide.pause();
  });
  observer?.observe(root);
  window.addEventListener('pagehide', () => { guide.pause(); observer?.disconnect(); });
  window.addEventListener('pageshow', event => { if (event.persisted) observer?.observe(root); });
})();
