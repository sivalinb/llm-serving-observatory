const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createGuide} = require('../observatory/static/guide.js');

function fixture(options = {}) {
  let next = 0;
  const timers = new Map(), changes = [];
  const guide = createGuide({...options,
    schedule(callback, delay) { assert.equal(delay, 12000); timers.set(++next, callback); return next; },
    cancel: id => timers.delete(id), onChange: (state, announce) => changes.push({state, announce})
  });
  return {guide, timers, changes, tick() {
    assert.equal(timers.size, 1);
    const [id, callback] = timers.entries().next().value; timers.delete(id); callback();
    return guide.snapshot();
  }};
}
test('reading is manual by default and previous/next remain bounded', () => {
  const f = fixture(); assert.equal(f.timers.size, 0);
  f.guide.previous(); assert.equal(f.guide.snapshot().index, 0);
  for (let i = 0; i < 10; i++) f.guide.next();
  assert.equal(f.guide.snapshot().index, 6); assert.equal(f.timers.size, 0);
  assert.throws(() => f.guide.select(7), RangeError);
  assert.throws(() => f.guide.select(-1), RangeError);
  assert.throws(() => f.guide.select(1.5), RangeError);
});
test('opt-in playback has one timer and stops at the final step', () => {
  const f = fixture(); f.guide.play(); f.guide.play();
  assert.equal(f.timers.size, 1);
  assert.deepEqual(Array.from({length: 6}, () => f.tick().index), [1, 2, 3, 4, 5, 6]);
  assert.equal(f.guide.snapshot().playing, false); assert.equal(f.timers.size, 0);
  f.guide.play(); assert.equal(f.guide.snapshot().index, 0); assert.equal(f.timers.size, 1);
  f.guide.destroy();
});
test('selection and pause cancel playback, including visibility/page-hide pauses', () => {
  const f = fixture(); f.guide.play(); f.guide.select(3);
  assert.equal(f.timers.size, 0); assert.equal(f.guide.snapshot().playing, false);
  f.guide.play(); f.guide.pause(); assert.equal(f.timers.size, 0);
  f.guide.next(); assert.equal(f.guide.snapshot().index, 4);
});
test('reduced motion prevents playback but never blocks manual navigation', () => {
  const f = fixture({reducedMotion: true}); f.guide.play(); assert.equal(f.timers.size, 0);
  f.guide.next(); assert.equal(f.guide.snapshot().index, 1);
  f.guide.setReducedMotion(false); assert.equal(f.timers.size, 0);
  f.guide.play(); assert.equal(f.timers.size, 1);
  f.guide.setReducedMotion(true); assert.equal(f.timers.size, 0);
});
test('automatic changes do not flood live announcements', () => {
  const f = fixture(); f.guide.play(); f.tick(); f.tick();
  assert.equal(f.changes.at(-1).announce, false);
  f.guide.select(4); assert.equal(f.changes.at(-1).announce, true);
});
test('destroy rejects stale callbacks and snapshots do not mutate state', () => {
  const f = fixture(); f.guide.snapshot().index = 6;
  assert.equal(f.guide.snapshot().index, 0); f.guide.play();
  const callback = [...f.timers.values()][0]; f.guide.destroy(); callback(); f.guide.play();
  assert.equal(f.timers.size, 0); assert.equal(f.guide.snapshot().index, 0);
});
