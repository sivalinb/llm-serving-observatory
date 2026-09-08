'use strict';
(() => {
  const GiB = 1024 ** 3;
  const fields = [
    ['input_tokens','Input tokens',4096,1,1048576,1,'fields'],
    ['output_tokens','Output tokens',512,1,131072,1,'fields'],
    ['concurrency','Active sequences',4,1,1024,1,'fields'],
    ['memory_gib','Device memory · GiB',24,1,2048,1,'fields'],
    ['weight_bits','Weight precision · bits',16,4,32,1,'fields',[4,8,16,32]],
    ['kv_bits','KV precision · bits',16,8,32,1,'fields',[8,16,32]],
    ['parameters_b','Parameters · billions',8,0.1,1000,0.1,'geometry'],
    ['layers','Layers',32,1,256,1,'geometry'],
    ['kv_heads','KV heads',8,1,256,1,'geometry'],
    ['head_dim','Head dimension',128,16,512,1,'geometry'],
    ['weight_overhead_pct','Weight overhead · %',10,0,100,1,'geometry'],
    ['workspace_gib','Workspace · GiB',2,0,256,0.1,'geometry'],
    ['reserve_pct','Safety reserve · %',10,0,50,1,'geometry'],
    ['memory_gb_s','HBM / VRAM · GB/s',1000,1,20000,1,'performance'],
    ['memory_efficiency','Memory efficiency · fraction',0.6,0.01,1,0.01,'performance'],
    ['compute_tflops','Compute · TFLOP/s',100,0.1,20000,0.1,'performance'],
    ['compute_efficiency','Compute efficiency · fraction',0.4,0.01,1,0.01,'performance'],
    ['link_gb_s','KV link · GB/s',25,0.001,1000,0.001,'performance'],
    ['link_latency_ms','Link setup · ms',3,0,1000,0.1,'performance']
  ];
  for (const [key,label,value,min,max,step,group,options] of fields) {
    const wrap=node('div'), lab=node('label',label); lab.htmlFor='hw-'+key;
    const input=node(options?'select':'input'); input.id=lab.htmlFor; input.name=key;
    if(options) for(const val of options){const option=node('option',String(val));option.value=val;input.append(option);}
    else {input.type='number';input.min=min;input.max=max;input.step=step;input.required=true;}
    input.value=value;wrap.append(lab,input);$('hardware-'+group).append(wrap);
  }
  let latest=null, baseline=null, sequence=0, timer=null, resourceBusy=false;
  const gib=value=>fmt(value/GiB,2)+' GiB';
  const read=()=>Object.fromEntries(fields.map(([key])=>[key,Number($('hw-'+key).value)]));
  const error=message=>{$('hardware-error').textContent=message;$('hardware-error').hidden=!message;};
  function invalidate(){sequence++;latest=null;$('hardware-pin').disabled=true;$('hardware-export').disabled=true;$('hardware-fit').textContent='INPUTS CHANGED · RECALCULATE';}
  async function calculate(){
    clearTimeout(timer);invalidate();const ticket=sequence;
    if(!$('hardware-form').reportValidity())return;
    error('');$('hardware-fit').textContent='CALCULATING';
    try {
      const response=await fetch('/api/hardware/estimate',{method:'POST',headers:headers(),body:JSON.stringify(read()),signal:AbortSignal.timeout(10000)});
      if(!response.ok)throw new Error(response.status===401?'Enter the lab API key in Live lab, then calculate again.':'Invalid configuration or unavailable service. Check the fields and retry.');
      const data=await response.json();if(ticket!==sequence)return;
      latest=data;render(data);$('hardware-pin').disabled=false;$('hardware-export').disabled=false;
    }catch(err){if(ticket===sequence){error(err.message);$('hardware-fit').textContent='RESULT UNAVAILABLE';}}
  }
  function render(data){
    const m=data.memory,p=data.performance;
    $('hardware-required').textContent=gib(m.required_bytes);
    $('hardware-capacity').textContent='of '+gib(m.capacity_bytes)+' planned capacity';
    $('hardware-fit').textContent=m.fits?'WITHIN MODELED BUDGET':'EXCEEDS MODELED BUDGET';
    $('hardware-fit').classList.toggle('over-budget',!m.fits);
    const parts=[['Weights',m.weights_bytes,'weights'],['Weight overhead',m.weight_overhead_bytes,'overhead'],['KV cache',m.kv_bytes,'kv'],['Workspace',m.workspace_bytes,'workspace'],['Reserve',m.reserve_bytes,'reserve'],['Free',Math.max(0,m.headroom_bytes),'free']];
    const scale=Math.max(m.required_bytes,m.capacity_bytes);
    $('hardware-budget-bar').replaceChildren();$('hardware-legend').replaceChildren();
    for(const [label,bytes,kind] of parts){
      if(bytes>0){const part=node('span',null,'memory-part '+kind);part.style.width=(bytes/scale*100)+'%';$('hardware-budget-bar').append(part);}
      const item=node('div',null,'memory-key'),swatch=node('span',null,'memory-swatch '+kind);
      item.append(swatch,node('span',label),node('strong',gib(bytes)));$('hardware-legend').append(item);
    }
    $('hardware-budget-bar').setAttribute('aria-label',parts.map(([label,bytes])=>label+' '+gib(bytes)).join('; '));
    $('hardware-headroom').textContent=(m.fits?gib(m.headroom_bytes)+' headroom. ':gib(-m.headroom_bytes)+' over capacity. ')+m.max_concurrency+' equal-length sequence(s) fit under these assumptions.';
    $('hardware-headroom').classList.toggle('over-budget',!m.fits);
    $('hardware-bounds').replaceChildren();
    for(const [label,value,note] of [['Memory-read floor',p.decode_memory_floor_ms,'weights + end-context KV / effective bandwidth'],['Dense-compute floor',p.decode_compute_floor_ms,'2 × parameters × batch / effective FLOP/s']]){
      const panel=node('article');panel.append(node('span',label),node('strong',value==null?'—':fmt(value,2)+' ms'),node('small',note));$('hardware-bounds').append(panel);
    }
    $('hardware-bound-note').textContent=m.fits?'Larger modeled term: '+p.decode_limiting_term.replaceAll('_',' ')+'. Optimistic decode step: '+fmt(p.decode_step_floor_ms,2)+' ms for one token per sequence; aggregate ceiling '+fmt(p.aggregate_output_ceiling_tps,0)+' tokens/s. Dense prefill compute floor: '+fmt(p.prefill_dense_compute_floor_ms/1000,2)+' s. Not measured TTFT or TPOT.':'Capacity is exceeded. Timing and throughput bounds are withheld: this single-device plan is infeasible without changing its assumptions.';
    $('hardware-transfer').textContent=gib(p.prompt_kv_transfer_bytes_per_request)+' / '+fmt(p.prompt_kv_transfer_floor_ms_per_request,2)+' ms';
    const sweepMax=Math.max(data.inputs.memory_gib,...data.context_sweep.map(s=>s.required_gib));
    $('hardware-sweep').replaceChildren();
    for(const s of data.context_sweep){const row=node('div',null,'sweep-row');const track=node('div',null,'sweep-track'),bar=node('span',null,'sweep-bar'),marker=node('span',null,'capacity-marker');bar.style.width=(s.required_gib/sweepMax*100)+'%';bar.classList.toggle('exceeded',s.required_gib>data.inputs.memory_gib);marker.style.left=(data.inputs.memory_gib/sweepMax*100)+'%';track.append(bar,marker);row.append(node('span',fmt(s.input_tokens,0)+' tokens'),track,node('strong',fmt(s.required_gib,1)+' GiB'));$('hardware-sweep').append(row);}
    $('hardware-assumptions').replaceChildren(...data.assumptions.map(a=>node('li',a)));
    $('hardware-sweep').setAttribute('aria-label',data.context_sweep.map(s=>fmt(s.input_tokens,0)+' input tokens: '+fmt(s.required_gib,2)+' GiB').join('; ')+'. Capacity '+data.inputs.memory_gib+' GiB.');
    compare();
  }
  function compare(){
    const root=$('hardware-comparison');root.replaceChildren();if(!baseline||!latest)return;
    const table=node('table'),head=node('thead'),tr=node('tr');for(const h of ['Metric / assumption','Saved baseline','Current'])tr.append(node('th',h));head.append(tr);const body=node('tbody');
    const rows=[['Input tokens',fmt(baseline.inputs.input_tokens,0),fmt(latest.inputs.input_tokens,0)],['Active sequences',baseline.inputs.concurrency,latest.inputs.concurrency],['Weight / KV bits',baseline.inputs.weight_bits+' / '+baseline.inputs.kv_bits,latest.inputs.weight_bits+' / '+latest.inputs.kv_bits],['Memory bandwidth · GB/s',baseline.inputs.memory_gb_s,latest.inputs.memory_gb_s],['Required incl. reserve',gib(baseline.memory.required_bytes),gib(latest.memory.required_bytes)],['Memory budget',baseline.memory.fits?'Fits':'Exceeded',latest.memory.fits?'Fits':'Exceeded'],['Decode step bound · ms',fmt(baseline.performance.decode_step_floor_ms,2),fmt(latest.performance.decode_step_floor_ms,2)]];
    for(const row of rows){const tr=node('tr');for(const value of row)tr.append(node('td',String(value)));body.append(tr);}table.append(head,body);root.append(table);
  }
  $('hardware-form').addEventListener('submit',e=>{e.preventDefault();calculate();});
  $('hardware-form').addEventListener('input',()=>{invalidate();clearTimeout(timer);timer=setTimeout(calculate,450);});
  $('hardware-pin').addEventListener('click',()=>{if(latest){baseline=structuredClone(latest);compare();$('hardware-experiment-note').textContent='Baseline saved in this page. Change one assumption, compare, then export the evidence.';}});
  $('hardware-export').addEventListener('click',()=>{if(latest)download({schema_version:'1.0',kind:'hardware_planning_comparison',exported_at:new Date().toISOString(),baseline,current:latest,warning:'Analytical estimates, not measured GPU results.'},'hardware-comparison.json');});
  const notes={baseline:'Baseline: inspect where the 24 GiB budget goes, then save it.',context:'Only prompt length changes to 32K. Watch KV growth exceed capacity; no real allocation or OOM is triggered.',quantize:'Only weight precision changes to 4-bit. Weight memory shrinks; KV precision and size stay unchanged. Accuracy and kernels require validation.',bandwidth:'Only memory bandwidth halves. Capacity is unchanged; the memory-bound decode estimate grows. Network handoff is unchanged.'};
  for(const button of document.querySelectorAll('[data-hardware-preset]'))button.addEventListener('click',()=>{for(const [key,,value] of fields)$('hw-'+key).value=value;const preset=button.dataset.hardwarePreset;if(preset==='context')$('hw-input_tokens').value=32768;if(preset==='quantize')$('hw-weight_bits').value=4;if(preset==='bandwidth')$('hw-memory_gb_s').value=500;$('hardware-experiment-note').textContent=notes[preset];calculate();});
  function clearResources(message){for(const id of ['cpu','rss','host','container'])$('resource-'+id).textContent='—';$('resource-status').textContent='MEASUREMENTS UNAVAILABLE';$('resource-note').textContent=message;}
  async function resources(){
    if(resourceBusy||$('view-hardware').hidden||document.hidden)return;resourceBusy=true;
    try{const response=await fetch('/api/hardware/resources',{headers:headers(),signal:AbortSignal.timeout(5000)});if(!response.ok)throw new Error(response.status===401?'Enter the lab API key in Live lab to view process measurements.':'Resource service unavailable.');const r=await response.json();if(r.status!=='ok'||r.sample_age_seconds>10)throw new Error('Resource sample unavailable or stale. Values are not replaced with zero.');
      $('resource-status').textContent='MEASURED · GATEWAY PROCESS';$('resource-cpu').textContent=r.process.cpu_cores==null?'Warming up':fmt(r.process.cpu_cores,3)+' cores';$('resource-rss').textContent=fmt(r.process.rss_bytes/1024**2,1)+' MiB';$('resource-host').textContent=gib(r.host.memory_available_bytes);const c=r.cgroup_namespace_root;$('resource-container').textContent=c.memory_current_bytes==null?'Unavailable':gib(c.memory_current_bytes)+' / '+(c.memory_limit_bytes==null?'no local limit':gib(c.memory_limit_bytes));$('resource-note').textContent='Last sampled '+new Date(r.sampled_at_unix*1000).toLocaleTimeString()+'. GPU / HBM: external exporter required. Host RAM is not container memory; short requests may fall between samples.';
    }catch(err){clearResources(err.message);}finally{resourceBusy=false;}
  }
  document.querySelector('[data-view="hardware"]').addEventListener('click',()=>{if(!latest)calculate();resources();});
  setInterval(resources,2000);
  window.addEventListener('hashchange',()=>{if(!$('view-hardware').hidden){if(!latest)calculate();resources();}});
  if(!$('view-hardware').hidden){calculate();resources();}
  // No hardware API calls until the user opens this view (or its deep link).
})();
