const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createTour} = require('../observatory/static/home.js');

function fixture(options = {}) {
  let next = 0;
  const timers = new Map(), changes = [];
  const tour = createTour({
    ...options,
    schedule: (callback, delay) => { assert.equal(delay, 3000); timers.set(++next, callback); return next; },
    cancel: id => timers.delete(id),
    onChange: (state, announce) => changes.push({state, announce})
  });
  return {tour, timers, changes, tick() {
    assert.equal(timers.size, 1, 'At most one animation timer');
    const [id, callback] = timers.entries().next().value; timers.delete(id); callback();
    return tour.snapshot();
  }};
}

test('combined journey skips transfer and returns to the start', () => {
  const f = fixture();
  assert.equal(f.tour.snapshot().phase, 'request');
  assert.deepEqual(Array.from({length: 5}, () => f.tick().phase), ['prefill', 'first', 'decode', 'observe', 'request']);
  assert.equal(f.tour.snapshot().output.length, 0);
  f.tour.destroy();
});

test('disaggregated journey contains a separate cache transfer', () => {
  const f = fixture(); f.tour.setMode('disaggregated');
  assert.deepEqual(Array.from({length: 6}, () => f.tick().phase), ['prefill', 'transfer', 'first', 'decode', 'observe', 'request']);
  f.tour.destroy();
});

test('output appears only at first visible content and later decode', () => {
  const f = fixture();
  assert.equal(f.tick().output.length, 0);
  assert.deepEqual(f.tick().output, ['Longer']);
  assert.equal(f.tick().output.join(' '), 'Longer prompts need more prefill work.');
  f.tour.destroy();
});

test('reduced motion prevents autoplay; visitors can step through statically', () => {
  const f = fixture({reducedMotion: true});
  assert.equal(f.timers.size, 0); assert.equal(f.tour.snapshot().playing, false);
  f.tour.selectPhase('decode');
  assert.equal(f.timers.size, 0); assert.equal(f.tour.snapshot().phase, 'decode');
  assert.equal(f.changes.at(-1).announce, true);
});

test('pause, restart and explicit play preserve one bounded timer', () => {
  const f = fixture(); f.tick(); f.tour.pause();
  assert.equal(f.timers.size, 0);
  f.tour.restart(); assert.equal(f.tour.snapshot().phase, 'request'); assert.equal(f.timers.size, 0);
  f.tour.play(); f.tour.play(); assert.equal(f.timers.size, 1);
  f.tour.restart(); assert.equal(f.timers.size, 1);
  f.tour.destroy(); assert.equal(f.timers.size, 0);
  f.tour.play(); assert.equal(f.timers.size, 0);
});

test('manual stage selection pauses, and mode changes reset the journey', () => {
  const f = fixture(); f.tour.selectPhase('observe');
  assert.equal(f.timers.size, 0); assert.equal(f.tour.snapshot().playing, false);
  f.tour.setMode('disaggregated'); assert.equal(f.tour.snapshot().phase, 'request');
  f.tour.selectPhase('transfer'); assert.equal(f.tour.snapshot().phase, 'transfer');
  f.tour.setMode('combined'); assert.equal(f.tour.snapshot().phase, 'request');
  assert.throws(() => f.tour.selectPhase('transfer'), RangeError);
  assert.throws(() => f.tour.setMode('__proto__'), RangeError);
});

test('automatic narration does not flood screen-reader live announcements', () => {
  const f = fixture(); f.tick(); f.tick();
  assert.ok(f.changes.every(change => !change.announce));
  f.tour.pause(); assert.equal(f.changes.at(-1).announce, true);
});

test('a changed reduced-motion preference stops the active timer', () => {
  const f = fixture(); f.tour.setReducedMotion(true);
  assert.equal(f.timers.size, 0); assert.equal(f.tour.snapshot().playing, false);
  f.tour.setReducedMotion(false); assert.equal(f.timers.size, 0);
});

test('returned snapshots cannot mutate the path or output', () => {
  const f = fixture(); const state = f.tour.snapshot(); state.steps.length = 0;
  assert.equal(f.tick().phase, 'prefill');
  const first = f.tick(); first.output[0] = 'changed';
  assert.deepEqual(f.tour.snapshot().output, ['Longer']); f.tour.destroy();
});
