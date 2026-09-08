const test = require('node:test');
const assert = require('node:assert/strict');
const {memoryBudget, latencyBudget, tokenLedger, simulateTraffic, percentile, matchesLesson} = require('../sites/academy.js');
const memory = {parameters:7,weightBits:4,layers:32,heads:8,dim:128,kvBits:16,context:4096,sequences:4,capacity:24,reserve:2};
const latency = {input:4096,cache:25,rate:8000,queue:50,size:512,bandwidth:8,setup:5,first:20,mode:'combined'};
const traffic = {interval:100,slots:2,maxQueue:6,ttftTarget:500,tpotTarget:30,hourlyCost:1};

test('memory uses binary units, KV heads and an explicit reserve', () => {
  const r = memoryBudget(memory);
  assert.equal(r.kv,2);
  assert.equal(r.weights,3.5e9 / 2**30);
  assert.equal(r.total,r.weights+r.kv+2);
  assert.equal(r.fits,true);
});
test('context and concurrent sequences multiply KV, not weights', () => {
  const base=memoryBudget(memory), r=memoryBudget({...memory,context:8192,sequences:8});
  assert.equal(r.kv,4*base.kv); assert.equal(r.weights,base.weights);
});
test('weight and KV quantization are independent', () => {
  const base=memoryBudget(memory), r=memoryBudget({...memory,weightBits:8});
  assert.equal(r.kv,base.kv); assert.equal(r.weights,base.weights*2);
  assert.equal(memoryBudget({...memory,kvBits:8}).kv,base.kv/2);
});
test('capacity overflow is shown and never converted into speed', () => {
  const r=memoryBudget({...memory,context:131072,sequences:32});
  assert.equal(r.fits,false); assert.ok(r.headroom<0); assert.equal(r.tokensPerSecond,undefined);
});
test('malformed, infinite, negative or fractional counts are rejected', () => {
  for(const patch of [{parameters:NaN},{capacity:Infinity},{heads:0},{sequences:1.5},{context:-1},{parameters:'7'}]) assert.throws(()=>memoryBudget({...memory,...patch}),RangeError);
});
test('combined mode has no transfer; disaggregated adds MiB/GiB conversion and setup', () => {
  const c=latencyBudget(latency),d=latencyBudget({...latency,mode:'disaggregated'});
  assert.equal(c.prefill,384); assert.equal(c.total,454); assert.equal(c.transfer,0);
  assert.equal(d.transfer,67.5); assert.equal(d.total,521.5);
});
test('warm prefix reduces modeled prompt work but does not erase independent handoff', () => {
  const r=latencyBudget({...latency,cache:100,mode:'disaggregated'});
  assert.equal(r.prefill,0);assert.equal(r.transfer,67.5);assert.equal(r.total,137.5);
  assert.throws(()=>latencyBudget({...latency,bandwidth:0}),RangeError);
  assert.throws(()=>latencyBudget({...latency,mode:'unknown'}),RangeError);
});
test('token subsets never count twice', () => {
  const r=tokenLedger({input:1000,cached:400,output:200,reasoning:50});
  assert.equal(r.total,1200);assert.equal(r.remainingOutput,150);
});
test('unknown token subsets remain null, including empty output', () => {
  assert.deepEqual(tokenLedger({input:0,cached:null,output:0,reasoning:null}),{input:0,cached:null,output:0,reasoning:null,total:0,remainingOutput:null});
});
test('invalid subset sizes and fractional tokens are rejected', () => {
  assert.throws(()=>tokenLedger({input:1,cached:2,output:2,reasoning:0}),RangeError);
  assert.throws(()=>tokenLedger({input:1,cached:0,output:2,reasoning:3}),RangeError);
  assert.throws(()=>tokenLedger({input:1.5,cached:0,output:2,reasoning:0}),RangeError);
});
test('toy traffic is deterministic, conserves requests and respects queue bounds', () => {
  const r=simulateTraffic(traffic);assert.deepEqual(r,simulateTraffic(traffic));
  assert.equal(r.requests.length,24);assert.equal(r.accepted+r.rejected,24);assert.ok(r.rejected>0);
  for(const request of r.requests){
    if(request.outcome!=='rejected'){assert.ok(request.start>=request.arrival);assert.equal(request.finish-request.start,840);}
    const waiting=r.requests.filter(q=>q.outcome!=='rejected'&&q.arrival<=request.arrival&&q.start>request.arrival);
    assert.ok(waiting.length<=traffic.maxQueue);
  }
});
test('no queue rejects overload; slow arrivals complete without wait', () => {
  const busy=simulateTraffic({...traffic,interval:10,maxQueue:0,slots:1});
  assert.equal(busy.accepted,1);assert.equal(busy.rejected,23);
  const quiet=simulateTraffic({...traffic,interval:2000,slots:1,maxQueue:0});
  assert.equal(quiet.accepted,24);assert.equal(quiet.good,24);assert.equal(quiet.p95,220);
});
test('goodput requires both targets and includes the full run in its denominator', () => {
  const r=simulateTraffic(traffic);
  assert.equal(r.goodput,r.good/r.duration);assert.equal(r.throughput,r.accepted/r.duration);
  assert.ok(r.goodput<=r.throughput);assert.equal(r.cost,r.duration/3600);
  const failed=simulateTraffic({...traffic,tpotTarget:19});assert.equal(failed.good,0);assert.equal(failed.costPerGood,null);
});
test('no useful requests gives undefined unit cost, not a free-service claim', () => {
  const r=simulateTraffic({...traffic,ttftTarget:1,hourlyCost:0});
  assert.equal(r.cost,0);assert.equal(r.costPerGood,null);
  assert.throws(()=>simulateTraffic({...traffic,slots:0}),RangeError);
});
test('nearest-rank percentile is descriptive and does not mutate input', () => {
  const a=[4,1,2,3];assert.equal(percentile(a,.95),4);assert.deepEqual(a,[4,1,2,3]);assert.equal(percentile([], .95),null);
});
test('search is case-insensitive, conjunctive and combined with track filtering', () => {
  assert.ok(matchesLesson('GPU HBM memory','Engine','hbm GPU','Engine'));
  assert.ok(matchesLesson('GPU HBM memory','Engine','  ','all'));
  assert.equal(matchesLesson('GPU HBM memory','Engine','CPU','all'),false);
  assert.equal(matchesLesson('GPU HBM memory','Engine','HBM','Operate'),false);
});
