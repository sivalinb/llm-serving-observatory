const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createFlow} = require('../sites/reliability.js');
test('manual by default, bounded steps, validated journey', () => {
  const flow = createFlow(); assert.equal(flow.snapshot().playing, false);
  for (let n=0;n<10;n++) flow.move(1);
  assert.equal(flow.snapshot().step, 4);
  flow.select('trace'); assert.equal(flow.snapshot().step, 0);
  flow.move(-1); assert.equal(flow.snapshot().step, 0);
  assert.throws(() => flow.select('private'), RangeError);
  assert.throws(() => flow.move(10), RangeError);
});
test('one timer, play ends, manual selection and reduced motion cancel', () => {
  const timers = new Map(); let id=0;
  const flow = createFlow({schedule(fn,ms){assert.equal(ms,9000);timers.set(++id,fn);return id;},cancel:id=>timers.delete(id)});
  flow.play();flow.play();assert.equal(timers.size,1);
  for(let n=0;n<4;n++){const [key,fn]=timers.entries().next().value;timers.delete(key);fn();}
  assert.equal(flow.snapshot().step,4);assert.equal(flow.snapshot().playing,false);assert.equal(timers.size,0);
  flow.play();assert.equal(flow.snapshot().step,0);flow.select('detect');assert.equal(timers.size,0);
  flow.play();flow.motion(true);assert.equal(timers.size,0);flow.play();assert.equal(flow.snapshot().playing,false);
  flow.motion(false);flow.play();flow.destroy();assert.equal(timers.size,0);
});
