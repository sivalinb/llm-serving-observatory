const test = require('node:test');
const assert = require('node:assert/strict');
const {display, metricValue, timelineParts, chartGeometry} = require('../observatory/static/observability.js');

test('zero is measured; missing and nonfinite remain unknown', () => {
  assert.equal(display(null), 'Unknown'); assert.equal(display(undefined), 'Unknown');
  assert.equal(display(NaN), 'Unknown'); assert.equal(display(Infinity), 'Unknown');
  assert.equal(display(0), '0');
  assert.equal(metricValue([], 'x'), null);
  assert.equal(metricValue([{name:'x',labels:{kind:'input'},value:0}], 'x', {kind:'input'}), 0);
  assert.equal(metricValue([{name:'x',labels:{kind:'input'},value:5},{name:'x',labels:{kind:'output'},value:3}], 'x', {kind:'input'}), 5);
});
test('timeline does not double-count retrieval or invent prefill spans', () => {
  assert.deepEqual(timelineParts({ttft_ms:20,duration_ms:50,retrieval_ms:2}), {first:20,streaming:30,firstPercent:40});
  for (const record of [{ttft_ms:null,duration_ms:50},{ttft_ms:60,duration_ms:50},{ttft_ms:0,duration_ms:0},{ttft_ms:-1,duration_ms:50}]) assert.equal(timelineParts(record), null);
});
test('chart domains support zeros, constant values, missing points and narrow layouts', () => {
  assert.equal(chartGeometry([{points:[[1,null]]}], 300), null);
  for (const width of [256,736]) {
    const g = chartGeometry([{points:[[100,0],[110,0],[120,null]]}], width);
    assert.equal(g.width,width); assert.ok(g.hi>g.lo);
    assert.ok(Number.isFinite(g.x(100))); assert.ok(Number.isFinite(g.y(0)));
    assert.ok(g.x(110) < width);
  }
});
