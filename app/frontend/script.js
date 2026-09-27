'use strict';

// Every visible result comes from the local API. Demo material is identified as manual.
const $ = (id) => document.getElementById(id);
const state = { capabilities: null, files: [], drafts: { 1: null, 2: null }, active: 1, busy: false };
const actionLabels = {
  heroDemoBtn: 'Открыть пример ↗', demoBtn: 'Открыть пример ↗',
  processBtn: 'Подготовить черновик с ИИ', compilePdfBtn: 'Собрать PDF ↗',
  genSimilarBtn: 'Подготовить вариант 2'
};
const currentDraft = () => state.drafts[state.active];
const selectedSubject = () => document.querySelector('input[name="subject"]:checked').value;
const settings = () => ({
  topic: $('topicInput').value.trim() || 'Рабочий лист',
  teacher_name: $('teacherNameInput').value.trim(),
  layout: $('layoutSelect').value,
  task_count: Number($('taskCount').value),
  subject: selectedSubject()
});
function applySettings(data) {
  $('topicInput').value = data.topic || '';
  $('teacherNameInput').value = data.teacher_name || '';
  $('layoutSelect').value = data.layout === '2col' ? '2col' : '1col';
  $('taskCount').value = String(Math.min(6, Math.max(1, Number(data.task_count) || 3)));
  $(data.subject === 'physics' ? 'subjectPhysics' : 'subjectMath').checked = true;
  updateSubjectDescription();
}
function fingerprint(draft) {
  return JSON.stringify([draft.code, draft.settings.topic, draft.settings.teacher_name, draft.settings.layout]);
}
function message(text, type = 'info') {
  const node = $('workspaceMessage');
  node.textContent = text;
  node.dataset.type = type;
  node.hidden = !text;
}
function editorIntoView() {
  $('editorContent').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 180000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: 'no-store' });
    let data;
    try { data = await response.json(); }
    catch { throw new Error('Сервер вернул ответ, который не удалось прочитать. Повторите запрос или обновите статус.'); }
    if (!response.ok || data.error) {
      const detail = typeof data.error === 'string' ? data.error : data.error?.message;
      const error = new Error(detail || 'Запрос не выполнен (HTTP ' + response.status + ').');
      error.code = data.code;
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Сервер не ответил за отведённое время. Черновик сохранён в редакторе; попробуйте снова.');
    if (error instanceof TypeError) throw new Error('Нет связи с локальным сервером. Проверьте, что он запущен, и повторите действие.');
    throw error;
  } finally { clearTimeout(timer); }
}
async function runAction(id, label, action) {
  if (state.busy) return;
  state.busy = true;
  const button = $(id);
  button.textContent = label;
  button.setAttribute('aria-busy', 'true');
  updateControls();
  try { await action(); }
  catch (error) {
    message(error.message || 'Не удалось выполнить действие.', 'error');
    if (error.status === 503) await loadStatus();
  } finally {
    state.busy = false;
    button.textContent = actionLabels[id];
    button.removeAttribute('aria-busy');
    updateControls();
  }
}
function updateControls() {
  const draft = currentDraft();
  const canAI = state.capabilities?.ai_ready === true;
  const canPDF = state.capabilities?.latex_ready === true;
  $('heroDemoBtn').disabled = state.busy;
  $('demoBtn').disabled = state.busy || state.capabilities?.demo_available === false;
  $('processBtn').disabled = state.busy || !canAI || state.files.length === 0;
  $('compilePdfBtn').disabled = state.busy || !canPDF || !draft?.code.trim() || !draft?.reviewed;
  $('genSimilarBtn').disabled = state.busy || !canAI || !state.drafts[1]?.code.trim();
  for (const id of ['uploadZone', 'clearFilesBtn', 'fileInput', 'reviewCheckbox', 'variant1Tab', 'variant2Tab', 'topicInput', 'teacherNameInput', 'layoutSelect', 'taskCount', 'variantDifficulty', 'subjectMath', 'subjectPhysics']) {
    $(id).disabled = state.busy;
  }
  $('latexEditorInput').readOnly = state.busy;
  if (!canPDF) $('reviewHint').textContent = state.capabilities ? 'Сборка PDF сейчас недоступна. Черновик можно редактировать.' : 'Проверяем доступность сборки PDF…';
  else if (!draft?.reviewed) $('reviewHint').textContent = 'Отметьте проверку, чтобы собрать этот вариант.';
  else $('reviewHint').textContent = 'Соберём PDF из проверенного содержимого редактора.';
}
function updateSubjectDescription() {
  $('demoDescription').textContent = selectedSubject() === 'physics'
    ? 'Задачи по физике с ответами. Можно менять условия и оформление.'
    : 'Задачи по математике с ответами. Можно менять условия и оформление.';
}
async function loadStatus() {
  $('refreshStatusBtn').disabled = true;
  try {
    const data = await api('/api/status');
    state.capabilities = data;
    const ai = data.ai_ready === true, pdf = data.latex_ready === true;
    const status = $('serverStatus');
    status.dataset.state = pdf && ai ? 'ready' : 'limited';
    status.lastElementChild.textContent = ai && pdf ? 'ИИ настроен · сборка PDF доступна' : pdf ? 'Сборка PDF доступна · пример без ИИ' : 'Редактор доступен · сборка PDF не настроена';
    $('aiHint').textContent = ai
      ? (data.ai_model ? data.ai_model + ' подготовит черновик по вашим фотографиям. ' : 'ИИ подготовит черновик по вашим фотографиям. ') + 'Перед сборкой проверьте условия и ответы.'
      : 'ИИ сейчас не настроен. Откройте пример — он подготовлен вручную и не требует ИИ.';
    $('pdfCapability').textContent = pdf ? 'LaTeX → PDF · локальная сборка доступна' : 'LaTeX → PDF · сборка пока недоступна';
    $('pdfStatusDot').className = 'mini-dot ' + (pdf ? 'ready' : 'offline');
    const limit = Number(data.max_files) || 10, mb = Number(data.max_upload_mb) || 20;
    $('uploadHelp').textContent = 'JPG или PNG · до ' + limit + ' файлов, всего ' + mb + ' МБ';
    updateControls();
  } catch {
    state.capabilities = null;
    $('serverStatus').dataset.state = 'error';
    $('serverStatus').lastElementChild.textContent = 'Не удалось связаться с сервером';
    $('aiHint').textContent = 'Возможности ИИ пока неизвестны. Запустите сервер и обновите статус.';
    $('pdfCapability').textContent = 'Статус сборки PDF неизвестен';
    $('pdfStatusDot').className = 'mini-dot offline';
    updateControls();
  } finally { $('refreshStatusBtn').disabled = false; }
}
function newDraft(code, source, meta, variant = 1) {
  if (typeof code !== 'string' || !code.trim()) throw new Error('Сервер не вернул задания. Попробуйте другое фото или откройте пример.');
  return { code, source, settings: { ...meta }, variant, reviewed: false, result: null, compiledFingerprint: null };
}
function showDraft(number, scroll = false) {
  state.active = number;
  const draft = currentDraft();
  if (!draft) return;
  applySettings(draft.settings);
  $('editorEmpty').hidden = true;
  $('editorContent').hidden = false;
  $('variant1Tab').setAttribute('aria-pressed', String(number === 1));
  $('variant2Tab').setAttribute('aria-pressed', String(number === 2));
  $('variant2Tab').hidden = !state.drafts[2];
  $('latexEditorInput').value = draft.code;
  $('reviewCheckbox').checked = draft.reviewed;
  const source = $('sourceBadge');
  source.classList.toggle('ai', draft.source === 'ai_draft');
  source.textContent = draft.source === 'manual_demo' ? 'Пример без ИИ' : draft.source === 'history' ? 'Из локальной истории' : 'Черновик ИИ';
  updateDraftStats();
  renderResults();
  updateControls();
  if (scroll) editorIntoView();
}
function updateDraftStats() {
  const draft = currentDraft();
  if (!draft) return;
  $('editorStats').textContent = new Intl.NumberFormat('ru-RU').format(draft.code.length) + ' символов';
  $('draftState').textContent = draft.result && draft.compiledFingerprint === fingerprint(draft) ? 'PDF соответствует этому черновику' : draft.result ? 'Изменения ещё не собраны в PDF' : 'Черновик ещё не собран';
}
function localFileURL(value) {
  if (typeof value !== 'string' || !value) return null;
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin || !['http:', 'https:'].includes(url.protocol)) return null;
    // Old locally stored rows can use the historical prefix.
    const path = url.pathname.replace(/^\/worksheet-api\/generated\//, '/api/generated/');
    return path.startsWith('/api/generated/') ? path + url.search : null;
  } catch { return null; }
}
function setResultLink(id, value) {
  const url = localFileURL(value);
  $(id).hidden = !url;
  if (url) $(id).href = url;
  else $(id).removeAttribute('href');
  return url;
}
function renderResults() {
  const draft = currentDraft();
  const fresh = draft?.result && draft.compiledFingerprint === fingerprint(draft);
  $('compileResults').hidden = !fresh;
  if (!fresh) {
    $('pdfPreview').removeAttribute('src');
    return;
  }
  const pdf = setResultLink('worksheetLink', draft.result.pdf_url);
  setResultLink('keysLink', draft.result.keys_url);
  setResultLink('texLink', draft.result.tex_url);
  $('compileResults').hidden = !pdf;
  if (pdf) $('pdfPreview').src = pdf;
  const warnings = Array.isArray(draft.result.warnings) ? draft.result.warnings.filter((x) => typeof x === 'string') : typeof draft.result.warnings === 'string' ? [draft.result.warnings] : [];
  $('compileWarnings').hidden = warnings.length === 0;
  $('compileWarnings').textContent = warnings.join(' ');
}
async function openDemo(buttonId) {
  await runAction(buttonId, 'Открываем пример…', async () => {
    const subject = selectedSubject();
    message('Загружаем учебный пример. Запрос к ИИ не выполняется.', 'pending');
    const data = await api('/api/demo?subject=' + encodeURIComponent(subject));
    const meta = { ...settings(), topic: data.topic || (subject === 'physics' ? 'Физика' : 'Математика'), subject };
    state.drafts = { 1: newDraft(data.latex_code, 'manual_demo', meta), 2: null };
    showDraft(1, true);
    message('Учебный пример подготовлен вручную. ИИ не использовался. Проверьте задания и ответы, затем соберите PDF.', 'success');
  });
}
function chooseFiles(files) {
  if (state.busy) return;
  const chosen = Array.from(files);
  const maxFiles = Number(state.capabilities?.max_files) || 10;
  const maxBytes = (Number(state.capabilities?.max_upload_mb) || 20) * 1024 * 1024;
  if (chosen.length > maxFiles) return message('Можно выбрать не более ' + maxFiles + ' файлов за один раз.', 'error');
  if (chosen.some((file) => !/\.(jpe?g|png)$/i.test(file.name))) return message('Сейчас принимаются фотографии JPG и PNG. Для PDF сначала подготовьте изображения страниц.', 'error');
  if (chosen.reduce((sum, file) => sum + file.size, 0) > maxBytes) return message('Общий размер файлов превышает допустимый лимит. Выберите меньше фотографий.', 'error');
  state.files = chosen;
  $('fileList').replaceChildren();
  for (const file of chosen) {
    const li = document.createElement('li');
    li.textContent = file.name + ' · ' + new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(file.size / 1024 / 1024) + ' МБ';
    $('fileList').append(li);
  }
  $('fileList').hidden = chosen.length === 0;
  $('clearFilesBtn').hidden = chosen.length === 0;
  if (chosen.length) message('Фотографии выбраны. Нажмите «Подготовить черновик с ИИ», чтобы начать обработку.');
  updateControls();
}
async function processFiles() {
  await runAction('processBtn', 'Готовим черновик…', async () => {
    const meta = settings(), form = new FormData();
    for (const file of state.files) form.append('files', file);
    for (const [name, value] of Object.entries(meta)) form.append(name, String(value));
    // The server owns provider/model selection; no API keys or model list in the browser.
    message('ИИ готовит черновик по вашим фотографиям. После ответа откроется редактор.', 'pending');
    const data = await api('/api/process', { method: 'POST', body: form });
    state.drafts = { 1: newDraft(data.latex_code, 'ai_draft', meta), 2: null };
    showDraft(1, true);
    message('Черновик получен. ИИ может ошибаться: проверьте условия, формулы и ответы до сборки.', 'success');
  });
}
async function compileCurrentDraft() {
  const draft = currentDraft();
  if (!draft?.reviewed || !draft.code.trim()) return;
  await runAction('compilePdfBtn', 'Собираем PDF…', async () => {
    draft.settings = settings();
    const sentFingerprint = fingerprint(draft);
    message('Собираем настоящий PDF из проверенного LaTeX. Дождитесь результата компиляции.', 'pending');
    const result = await api('/api/compile', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latex_code: draft.code, ...draft.settings, is_variant2: state.active === 2 })
    });
    if (!localFileURL(result.pdf_url)) throw new Error('Сервер не вернул доступную ссылку на PDF. Черновик остался в редакторе.');
    draft.result = result;
    draft.compiledFingerprint = sentFingerprint;
    renderResults();
    updateDraftStats();
    message('PDF собран. Откройте рабочий лист и проверьте размещение заданий перед печатью.', 'success');
    await loadHistory();
  });
}
async function generateSimilar() {
  const first = state.drafts[1];
  if (!first?.code.trim()) return;
  await runAction('genSimilarBtn', 'Готовим вариант 2…', async () => {
    const form = new FormData();
    form.append('original_text', first.code);
    form.append('difficulty', $('variantDifficulty').value);
    for (const [key, value] of Object.entries(first.settings)) form.append(key, String(value));
    message('ИИ готовит похожие задачи по первому варианту. PDF будет собран только после вашей проверки.', 'pending');
    const result = await api('/api/generate_similar', { method: 'POST', body: form });
    state.drafts[2] = newDraft(result.latex_code, 'ai_draft', first.settings, 2);
    showDraft(2, true);
    message('Вариант 2 открыт для проверки. Убедитесь, что условия, ответы и сложность подходят классу, затем соберите PDF.', 'success');
  });
}
function historyElement(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function historyLink(label, path, style = 'subtle') {
  const url = localFileURL(path);
  if (!url) return null;
  const link = historyElement('a', 'button small ' + style, label);
  link.href = url; link.target = '_blank'; link.rel = 'noopener';
  return link;
}
async function loadHistory() {
  $('refreshHistoryBtn').disabled = true;
  try {
    const data = await api('/api/history?limit=10');
    const container = $('historyContainer');
    container.replaceChildren();
    if (!Array.isArray(data.history) || data.history.length === 0) {
      container.append(historyElement('p', 'history-empty', 'Здесь появятся собранные рабочие листы. Начните с примера или своих заданий.'));
      return;
    }
    for (const item of data.history) {
      const row = historyElement('article', 'history-item');
      const info = historyElement('div', 'history-info');
      info.append(historyElement('span', 'history-icon', 'PDF'));
      const text = historyElement('div', '');
      text.append(historyElement('h3', '', item.topic || 'Рабочий лист'));
      const date = new Date(String(item.created_at || '').replace(' ', 'T'));
      const when = Number.isNaN(date.getTime()) ? 'Сохранённый лист' : date.toLocaleString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
      text.append(historyElement('p', '', when + (item.teacher_name ? ' · ' + item.teacher_name : '')));
      info.append(text);
      const actions = historyElement('div', 'history-actions');
      for (const [label, path, style] of [['Рабочий лист ↗', item.pdf_url, 'dark'], ['Ответы ↗', item.keys_url, 'subtle']]) {
        const link = historyLink(label, path, style); if (link) actions.append(link);
      }
      if (typeof item.latex_code === 'string' && item.latex_code.trim()) {
        const edit = historyElement('button', 'button small subtle', 'В редактор');
        edit.type = 'button';
        edit.addEventListener('click', () => {
          if (state.busy) return;
          state.drafts = { 1: newDraft(item.latex_code, 'history', { topic: item.topic || 'Рабочий лист', teacher_name: item.teacher_name || '', layout: '1col', task_count: 3, subject: selectedSubject() }), 2: null };
          showDraft(1, true);
          message('Сохранённый текст открыт в редакторе. Проверьте его перед сборкой новой версии.');
        });
        actions.append(edit);
      }
      row.append(info, actions); container.append(row);
    }
  } catch (error) {
    $('historyContainer').replaceChildren(historyElement('p', 'history-empty', 'История пока недоступна. ' + error.message));
  } finally { $('refreshHistoryBtn').disabled = false; }
}

const texLink = document.createElement('a');
texLink.id = 'texLink'; texLink.className = 'button subtle small'; texLink.textContent = 'Полный .tex ↗';
texLink.target = '_blank'; texLink.rel = 'noopener'; texLink.hidden = true;
$('keysLink').after(texLink);

$('heroDemoBtn').addEventListener('click', () => openDemo('heroDemoBtn'));
$('demoBtn').addEventListener('click', () => openDemo('demoBtn'));
$('uploadZone').addEventListener('click', () => $('fileInput').click());
$('fileInput').addEventListener('change', (event) => chooseFiles(event.target.files));
$('clearFilesBtn').addEventListener('click', () => { $('fileInput').value = ''; chooseFiles([]); });
for (const name of ['dragenter', 'dragover']) $('uploadZone').addEventListener(name, (event) => {
  event.preventDefault(); if (!state.busy) $('uploadZone').classList.add('drag-over');
});
for (const name of ['dragleave', 'drop']) $('uploadZone').addEventListener(name, (event) => {
  event.preventDefault(); $('uploadZone').classList.remove('drag-over');
});
$('uploadZone').addEventListener('drop', (event) => chooseFiles(event.dataTransfer.files));
$('processBtn').addEventListener('click', processFiles);
$('compilePdfBtn').addEventListener('click', compileCurrentDraft);
$('genSimilarBtn').addEventListener('click', generateSimilar);
$('refreshStatusBtn').addEventListener('click', loadStatus);
$('refreshHistoryBtn').addEventListener('click', loadHistory);
$('variant1Tab').addEventListener('click', () => { if (!state.busy) showDraft(1); });
$('variant2Tab').addEventListener('click', () => { if (!state.busy) showDraft(2); });
$('latexEditorInput').addEventListener('input', () => {
  const draft = currentDraft(); if (!draft) return;
  draft.code = $('latexEditorInput').value; draft.reviewed = false;
  $('reviewCheckbox').checked = false; updateDraftStats(); renderResults(); updateControls();
});
$('reviewCheckbox').addEventListener('change', () => {
  if (currentDraft()) currentDraft().reviewed = $('reviewCheckbox').checked;
  updateControls();
});
for (const id of ['topicInput', 'teacherNameInput', 'layoutSelect', 'taskCount']) {
  $(id).addEventListener(id.endsWith('Input') ? 'input' : 'change', () => {
    const draft = currentDraft(); if (!draft) return;
    draft.settings = { ...settings(), subject: draft.settings.subject };
    draft.reviewed = false; $('reviewCheckbox').checked = false;
    updateDraftStats(); renderResults(); updateControls();
  });
}
for (const element of document.querySelectorAll('input[name="subject"]')) element.addEventListener('change', updateSubjectDescription);
$('copyLatexBtn').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('latexEditorInput').value);
    $('copyLatexBtn').textContent = 'Скопировано';
    setTimeout(() => { $('copyLatexBtn').textContent = 'Копировать'; }, 1800);
  } catch {
    $('latexEditorInput').focus(); $('latexEditorInput').select();
    message('Текст выделен. Нажмите Ctrl+C, чтобы скопировать LaTeX.');
  }
});
$('latexEditorInput').addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !$('compilePdfBtn').disabled) { event.preventDefault(); compileCurrentDraft(); }
});
updateSubjectDescription();
updateControls();
Promise.allSettled([loadStatus(), loadHistory()]);
