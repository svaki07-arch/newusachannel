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
function sceneList() { return [...new Set($('scenes').value.split('\n').map(s => s.trim()).filter(Boolean))]; }
function scriptInfo() {
  const text = $('script').value.trim();
  const words = text ? text.split(/\s+/).length : 0;
  const wpm = Number($('words-per-minute').value) || 140;
  const perFrame = Math.max(1, Math.round(wpm * Number($('frame-seconds').value) / 60));
  return {active: words > 0, frames: Math.ceil(words / perFrame), seconds: Math.round(words * 60 / wpm)};
}
function budget() {
  const info = scriptInfo();
  $('count-value').textContent = $('count').value;
  $('scenes').disabled = info.active;
  $('example-scenes').disabled = info.active;
  $('count').disabled = info.active;
  if (info.active) {
    $('candidate-budget').textContent = `Примерно ${info.seconds} секунд · ${info.frames} кадров × ${$('script-candidates').value} = до ${info.frames * Number($('script-candidates').value)} кандидатов. Планирование и AI-проверки оплачиваются отдельно.`;
  } else {
    const sections = sceneList().length || 1;
    $('candidate-budget').textContent = `${sections} раздел(ов) × ${$('count').value} = до ${sections * Number($('count').value)} кандидатов. Без видимых водяных знаков; AI может ошибаться.`;
  }
}
for (const id of ['count', 'scenes', 'script', 'frame-seconds', 'words-per-minute', 'script-candidates']) $(id).oninput = budget;
$('example-scenes').onclick = () => { $('scenes').value = $('scenes').placeholder; budget(); };
budget();
$('score').oninput = () => $('score-value').textContent = `${$('score').value} / 10`;
function render(job) {
  $('status').textContent = job.status.toUpperCase();
  $('logs').textContent = job.logs.join('\n'); $('logs').scrollTop = $('logs').scrollHeight;
  $('progress').max = job.total || 1; $('progress').value = job.processed;
  $('approved').textContent = job.images.length; $('empty').hidden = job.images.length > 0;
  $('gallery').replaceChildren();
  const sectionGrids = new Map();
  for (const section of (job.sections || [])) {
    const wrapper = document.createElement('section'); wrapper.className = 'section-gallery';
    const heading = document.createElement('h3');
    heading.textContent = `${section.name} · ${section.approved} кадров${section.status === 'failed' ? ' · ошибка поиска' : ''}`;
    const grid = document.createElement('div'); grid.className = 'gallery';
    wrapper.append(heading);
    if (section.text) { const narration = document.createElement('p'); narration.className = 'hint'; narration.textContent = section.text; wrapper.append(narration); }
    wrapper.append(grid); $('gallery').append(wrapper);
    sectionGrids.set(section.name, grid);
  }
  for (const item of job.images) {
    const card = document.createElement('article'); card.className = 'card';
    const img = document.createElement('img'); img.src = item.url; img.alt = item.reason; img.loading = 'lazy';
    const text = document.createElement('p'); text.textContent = `${item.selected ? "★ Основной кадр · " : ""}${item.score}/10 · ${item.reason}`;
    const link = document.createElement('a'); link.href = item.source; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Original source ↗';
    card.append(img, text, link); (sectionGrids.get(item.section) || $('gallery')).append(card);
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
    const info = scriptInfo();
    if (!$('query').value.trim() && !info.active) throw new Error('Введи тему или текст сценария.');
    if (info.active && (info.frames > 60 || info.frames * Number($('script-candidates').value) > 1000)) throw new Error('Максимум 60 кадров и 1000 кандидатов: сократи текст или уменьши число кандидатов.');
    if (!info.active && (sceneList().length > 20 || Math.max(1, sceneList().length) * Number($('count').value) > 1000)) throw new Error('Уменьши число разделов или кандидатов: максимум 20 разделов и 1000 кандидатов.');
    const job = await api('/api/jobs', {method:'POST', body:JSON.stringify({query:$('query').value, location:$('location').value, event_date:$('event-date').value, scenes:info.active ? [] : sceneList(), script:$('script').value, frame_seconds:Number($('frame-seconds').value), words_per_minute:Number($('words-per-minute').value), script_candidates:Number($('script-candidates').value), maximum:Number($('count').value), threshold:Number($('score').value)})});
    sessionStorage.setItem('job', job.id); poll(job.id);
  } catch (e) { error(e); $('start').disabled = false; }
};
const previous = sessionStorage.getItem('job');
if (previous) { $('start').disabled = true; poll(previous); }
