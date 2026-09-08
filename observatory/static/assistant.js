(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let key = '', configured = false, controller = null;
  const text = (id, value) => { $(id).textContent = value; };
  const number = value => value == null ? 'unknown' : value.toLocaleString();
  const ms = value => value == null ? '—' : `${Math.round(value).toLocaleString()} ms`;
  function controls() {
    $('ask-button').disabled = !key || !configured || !!controller;
    $('search-button').disabled = !key || !!controller;
    $('refresh-history').disabled = !key;
    $('delete-history').disabled = !key || !!controller;
    $('stop-button').hidden = !controller;
  }
  async function api(path, options = {}) {
    const response = await fetch('/api/service/' + path, {
      ...options, headers: {'Content-Type': 'application/json', ...(key ? {Authorization: 'Bearer ' + key} : {}), ...options.headers}
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status})`);
    }
    return response;
  }
  function sources(items) {
    $('sources').replaceChildren();
    if (!items.length) { text('sources', 'No relevant approved references found.'); return; }
    for (const item of items) {
      const card = document.createElement('article'); card.className = 'source';
      const link = document.createElement('a'); link.textContent = `[${item.id}] ${item.title} ↗`;
      // The server owns source URLs; still enforce the exact project prefix at the renderer.
      if (item.url.startsWith('https://github.com/sivalinb/llm-serving-observatory/blob/main/')) link.href = item.url;
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      const excerpt = document.createElement('p'); excerpt.textContent = item.excerpt;
      card.append(link, excerpt); $('sources').append(card);
    }
  }
  async function refresh() {
    if (!key) return;
    const me = await (await api('me')).json();
    $('account').hidden = false;
    text('account-name', me.user.name);
    text('requests-used', `${number(me.usage.requests_today)} / ${number(me.user.requests)}`);
    text('tokens-used', `${number(me.usage.quota_tokens_today)} / ${number(me.user.tokens)}`);
    const data = await (await api('history')).json();
    $('request-rows').replaceChildren();
    for (const r of data.records) {
      const tr = document.createElement('tr');
      for (const value of [r.id.slice(0, 10), r.status, ms(r.ttft_ms), ms(r.duration_ms), `${number(r.tokens.input)} / ${number(r.tokens.output)}`, number(r.tokens.reasoning), r.citations]) {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      }
      $('request-rows').append(tr);
    }
    if (!data.records.length) {
      const tr = document.createElement('tr'), td = document.createElement('td');
      td.colSpan = 7; td.textContent = 'No request metadata yet. Search does not invoke the model.';
      tr.append(td); $('request-rows').append(tr);
    }
    controls();
  }
  function reveal(value) { key = value; $('new-key').value = value; $('key-reveal').hidden = false; }
  function clearWorkspace() {
    controller?.abort(); key = ''; $('account').hidden = true; $('key-reveal').hidden = true;
    $('new-key').value = ''; $('access-key').value = ''; $('question').value = '';
    text('answer', ''); $('receipt').hidden = true; $('request-rows').replaceChildren();
    sources([]); controls();
  }
  $('login-form').addEventListener('submit', async event => {
    event.preventDefault(); const entered = $('access-key').value.trim(); clearWorkspace(); key = entered;
    try { await refresh(); text('access-message', 'Workspace connected.'); }
    catch (error) { clearWorkspace(); text('access-message', error.message); }
  });
  $('invite-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const result = await (await api('redeem', {method: 'POST', body: JSON.stringify({invite: $('invite-code').value.trim(), name: $('display-name').value.trim()})})).json();
      clearWorkspace(); reveal(result.api_key); $('invite-code').value = ''; await refresh();
      text('access-message', 'Invite activated. Save the key shown above.');
    } catch (error) { text('access-message', error.message); }
  });
  $('hide-key').onclick = () => { $('new-key').value = ''; $('key-reveal').hidden = true; };
  $('sign-out').onclick = () => { clearWorkspace(); text('access-message', 'Signed out on this page.'); };
  $('rotate-key').onclick = async () => {
    if (!confirm('Revoke your old key and create a new one? Save the new key before leaving.')) return;
    try { reveal((await (await api('rotate-key', {method: 'POST'})).json()).api_key); }
    catch (error) { text('access-message', error.message); }
  };
  for (const button of document.querySelectorAll('[data-question]')) button.onclick = () => {
    $('question').value = button.dataset.question; $('question').focus();
  };
  // Omit max_tokens so the server's deployment-specific default is authoritative.
  const questionBody = () => JSON.stringify({question: $('question').value.trim()});
  $('search-button').onclick = async () => {
    if (!$('question-form').reportValidity()) return;
    try {
      sources((await (await api('search', {method: 'POST', body: questionBody()})).json()).sources);
      text('answer', ''); $('receipt').hidden = true;
      text('answer-state', 'Document search complete. No model call or generation tokens used.');
    } catch (error) { text('answer-state', error.message); }
  };
  $('question-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!key || !configured || controller) return;
    controller = new AbortController(); controls(); text('answer', ''); $('receipt').hidden = true;
    text('answer-state', 'Retrieving references and waiting for the first visible model output…');
    let completed = false, hadError = false;
    try {
      const response = await api('answer', {method: 'POST', body: questionBody(), signal: controller.signal,
        headers: {'Idempotency-Key': crypto.randomUUID()}});
      const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const chunk = await reader.read(); buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
        let end;
        while ((end = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, end); buffer = buffer.slice(end + 2);
          if (!block.startsWith('data: ')) continue;
          const item = JSON.parse(block.slice(6));
          if (item.type === 'sources') sources(item.sources);
          if (item.type === 'delta') { $('answer').append(document.createTextNode(item.content)); text('answer-state', 'Streaming real model output…'); }
          if (item.type === 'error') { hadError = true; text('answer-state', item.message); }
          if (item.type === 'result') {
            completed = true; const r = item.record; $('receipt').hidden = false;
            text('receipt', `TTFT ${ms(r.ttft_ms)} · Total ${ms(r.duration_ms)} · Input ${number(r.tokens.input)} · Output ${number(r.tokens.output)} · Cached input ${number(r.tokens.cached_input)} · Reasoning ${number(r.tokens.reasoning)}\nCitation IDs: ${r.citations} (not a factual check) · Request ${r.id}\nTrace ${r.trace_id || 'unavailable'}`);
            if (!hadError) {
              const warnings = [];
              if (r.finish_reason === 'length') warnings.push('Output cap reached; the answer may be incomplete.');
              if (r.citations !== 'present') warnings.push('Missing or invalid source citations: treat this answer as unverified.');
              text('answer-state', warnings.length ? warnings.join(' ') : 'Answer complete. Verify claims against the references below.');
            }
          }
        }
        if (chunk.done) break;
      }
      if (!completed) throw new Error('Stream interrupted before a final receipt. Check history before retrying.');
    } catch (error) {
      text('answer-state', error.name === 'AbortError' ? 'Stopped. Uncertain work retains its quota reservation.' : error.message);
    } finally { controller = null; controls(); try { await refresh(); } catch { /* Preserve stream error. */ } }
  });
  $('stop-button').onclick = () => controller?.abort();
  $('refresh-history').onclick = () => refresh().catch(error => text('access-message', error.message));
  $('delete-history').onclick = async () => {
    if (!confirm('Delete your stored request metadata? Minimal quota records remain for up to 90 days.')) return;
    try { await api('history', {method: 'DELETE'}); await refresh(); }
    catch (error) { text('access-message', error.message); }
  };
  api('status').then(r => r.json()).then(status => {
    configured = status.inference === 'configured';
    text('backend-status', configured ? 'CPU model configured' : 'Document search ready');
    text('backend-note', configured ? `Real llama.cpp inference is enabled. First answers may take time on CPU. Up to ${status.max_output_tokens} output tokens, one answer at a time, ${status.deadline_seconds}s deadline.` : 'AI answers are off until an operator starts the CPU model. Search is available with an invite.');
    controls();
  }).catch(() => { text('backend-status', 'Service unavailable'); text('backend-note', 'Try reloading after the service recovers.'); });
})();
