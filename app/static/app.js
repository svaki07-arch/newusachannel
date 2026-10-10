const $ = id => document.getElementById(id);
let timer;
async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Invalid request');
  return data;
}
function error(e) { $('message').textContent = e.message; }
function showSettings(s) {
  $('provider').value = s.provider; $('cx').value = s.google_cx;
  $('key-status').textContent = `OpenAI: ${s.has_openai_key ? 'saved' : 'missing'} · Search: ${s.has_search_key ? 'saved' : 'missing'}`;
}
api('/api/settings').then(showSettings).catch(error);
$('settings').onsubmit = async event => {
  event.preventDefault(); $('message').textContent = '';
  try {
    showSettings(await api('/api/settings', {method: 'POST', body: JSON.stringify({openai_key: $('openai').value, search_key: $('searchkey').value, google_cx: $('cx').value, provider: $('provider').value})}));
    $('openai').value = ''; $('searchkey').value = '';
  } catch (e) { error(e); }
};
$('clear').onclick = async () => {
  try { await api('/api/settings', {method: 'DELETE'}); showSettings(await api('/api/settings')); } catch(e) { error(e); }
};
$('count').oninput = () => $('count-value').textContent = $('count').value;
$('score').oninput = () => $('score-value').textContent = `${$('score').value} / 10`;
function render(job) {
  $('status').textContent = job.status.toUpperCase();
  $('logs').textContent = job.logs.join('\n'); $('logs').scrollTop = $('logs').scrollHeight;
  $('progress').max = job.total || 1; $('progress').value = job.processed;
  $('approved').textContent = job.images.length; $('empty').hidden = job.images.length > 0;
  $('gallery').replaceChildren();
  for (const item of job.images) {
    const card = document.createElement('article'); card.className = 'card';
    const img = document.createElement('img'); img.src = item.url; img.alt = item.reason; img.loading = 'lazy';
    const text = document.createElement('p'); text.textContent = `${item.score}/10 · ${item.reason}`;
    const link = document.createElement('a'); link.href = item.source; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Original source ↗';
    card.append(img, text, link); $('gallery').append(card);
  }
  $('zip').hidden = !job.zip_url; if (job.zip_url) $('zip').href = job.zip_url;
}
async function poll(id) {
  try {
    const job = await api(`/api/jobs/${id}`); render(job);
    if (job.status === 'running') timer = setTimeout(() => poll(id), 1200);
    else { $('start').disabled = false; sessionStorage.removeItem('job'); }
  } catch (e) { error(e); $('start').disabled = false; }
}
$('workflow').onsubmit = async event => {
  event.preventDefault(); $('message').textContent = ''; $('start').disabled = true; clearTimeout(timer);
  try {
    const job = await api('/api/jobs', {method:'POST', body:JSON.stringify({query:$('query').value, refinement:$('refinement').value, criteria:$('criteria').value, no_watermarks:$('no-watermarks').checked, maximum:Number($('count').value), threshold:Number($('score').value)})});
    sessionStorage.setItem('job', job.id); poll(job.id);
  } catch (e) { error(e); $('start').disabled = false; }
};
const previous = sessionStorage.getItem('job');
if (previous) { $('start').disabled = true; poll(previous); }
