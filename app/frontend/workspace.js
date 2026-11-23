"use strict";
// Progressive layout: all actions still use the existing editor and API.
(() => {
  const nav = document.querySelector('.topbar nav');
  for (const [id, text] of [['createNav', 'МАТЕРИАЛЫ'], ['batchNav', 'УЧЕБНЫЙ ПРОЦЕСС'], ['analyticsNav', 'РЕЗУЛЬТАТЫ']]) {
    const label = node('span', text, 'nav-section');
    label.setAttribute('aria-hidden', 'true');
    $(id).before(label);
  }
  $('studentNav')?.classList.add('nav-student-switch');
  document.querySelector('.brand-caption').textContent = 'К уроку — всё готово';

  const tools = document.querySelector('.account-tools');
  const profile = document.querySelector('.account-profile');
  const accountMenu = node('details', undefined, 'account-menu');
  const accountSummary = node('summary');
  accountSummary.setAttribute('aria-label', 'Меню профиля');
  accountSummary.append(profile, listokIcon('chevronDown'));
  accountMenu.append(accountSummary, document.querySelector('.account-actions'));
  tools.append(accountMenu);
  accountMenu.addEventListener('click', event => {
    if (event.target.closest('button')) accountMenu.open = false;
  });
  document.addEventListener('click', event => {
    if (!accountMenu.contains(event.target)) accountMenu.open = false;
    for (const menu of document.querySelectorAll('.material-more[open]'))
      if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const menus = [accountMenu, ...document.querySelectorAll('.material-more[open]')].filter(menu => menu.open);
    const focusedMenu = menus.find(menu => menu.contains(document.activeElement));
    for (const menu of menus) menu.open = false;
    if (focusedMenu) {
      focusedMenu.querySelector('summary')?.focus();
      event.preventDefault();
    }
  });

  // Help opens on request, leaving the first screen for the teacher's task.
  const video = document.querySelector('.video-guide-card');
  const videoFrame = video.querySelector('iframe');
  const videoSource = videoFrame.getAttribute('src');
  videoFrame.src = 'about:blank';
  const videoDialog = node('dialog', undefined, 'guide-dialog');
  videoDialog.setAttribute('aria-labelledby', 'videoGuideTitle');
  const closeVideo = classButton('Закрыть', () => videoDialog.close(), 'ghost');
  closeVideo.classList.add('guide-close');
  video.querySelector('.video-guide-details').open = true;
  video.querySelector('.video-guide-details > summary').hidden = true;
  videoDialog.append(closeVideo, video);
  document.body.append(videoDialog);
  const videoButton = classButton('Видеоинструкция', () => {
    videoFrame.src = videoSource;
    videoDialog.showModal();
  }, 'ghost');
  videoButton.replaceChildren(listokIcon('play'), node('span', 'Видеоинструкция', 'guide-label'));
  videoButton.title = 'Видеоинструкция';
  document.querySelector('.workspace-heading').append(videoButton);
  videoDialog.addEventListener('click', event => { if (event.target === videoDialog) videoDialog.close(); });
  videoDialog.addEventListener('close', () => { videoFrame.src = 'about:blank'; });

  // One input method at a time. Switching never removes entered text or files.
  const uploadPanel = node('div', undefined, 'source-panel'); uploadPanel.id = 'sourceUploadPanel';
  const textPanel = node('div', undefined, 'source-panel'); textPanel.id = 'sourceTextPanel';
  const textDetails = document.querySelector('.text-input');
  const sourceTabs = node('div', undefined, 'source-tabs');
  sourceTabs.setAttribute('role', 'tablist'); sourceTabs.setAttribute('aria-label', 'Источник заданий');
  const sourceHint = node('p', undefined, 'quiet'); sourceHint.id = 'sourceModeHint';
  sourceHint.setAttribute('role', 'status'); sourceHint.hidden = true;
  $('dropZone').before(sourceTabs, sourceHint, uploadPanel, textPanel);
  $('recognizeBtn').setAttribute('aria-describedby', sourceHint.id);
  uploadPanel.append($('dropZone'), document.querySelector('.camera-row'), $('fileList'));
  for (const child of [...textDetails.children]) if (child.tagName !== 'SUMMARY') textPanel.append(child);
  textDetails.remove();
  const panels = [uploadPanel, textPanel];
  const tabButtons = [];
  const setSource = index => {
    state.sourceMode = index === 0 ? 'files' : 'text';
    panels.forEach((panel, i) => { panel.hidden = i !== index; });
    tabButtons.forEach((button, i) => { button.setAttribute('aria-selected', String(i === index)); button.tabIndex = i === index ? 0 : -1; });
    syncInputCounts();
  };
  for (const [i, text, iconName] of [[0, 'Фото или PDF', 'photo'], [1, 'Текст и формулы', 'math']]) {
    const button = node('button', undefined, 'source-tab'); button.type = 'button';
    button.id = 'sourceTab' + i; button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', panels[i].id);
    panels[i].setAttribute('role', 'tabpanel'); panels[i].setAttribute('aria-labelledby', button.id);
    button.append(listokIcon(iconName), node('span', text), node('span', '', 'source-count'));
    button.addEventListener('click', () => setSource(i));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - i;
      setSource(next); tabButtons[next].focus();
    });
    tabButtons.push(button); sourceTabs.append(button);
  }
  setSource($('sourceText').value.trim() ? 1 : 0);
  function syncInputCounts() {
    tabButtons[0].querySelector('.source-count').textContent = state.files.length || '';
    const hasText = !!$('sourceText').value.trim();
    tabButtons[1].querySelector('.source-count').textContent = hasText ? '•' : '';
    const otherSource = state.sourceMode === 'text' ? state.files.length > 0 : hasText;
    sourceHint.hidden = !otherSource;
    sourceHint.textContent = !otherSource ? '' : state.sourceMode === 'text'
      ? 'Отправится только текст. Файлы сохранены во вкладке «Фото или PDF».'
      : 'Отправятся только файлы. Текст сохранён во вкладке «Текст и формулы».';
  }
  $('sourceText').addEventListener('input', syncInputCounts);
  new MutationObserver(syncInputCounts).observe($('fileList'), {childList: true});

  // A short example is a secondary action, not another large block.
  const example = $('demoBtn');
  example.className = 'button ghost source-example'; example.textContent = 'Взять пример';
  document.querySelector('#step1 .panel-heading').append(example);
  document.querySelector('.demo-strip').remove();
  document.querySelector('.setup-settings').append(document.querySelector('.teacher-instructions'));
  // The desktop preview lives in a sidebar that disappears at tablet widths.
  // Reuse the live sheet for both mobile entry points so its settings stay in sync.
  const sheetPreview = document.querySelector('.studio-preview');
  const previewSidebar = sheetPreview.parentElement;
  const sheetDialog = node('dialog', undefined, 'sheet-preview-dialog');
  const previewHeading = sheetPreview.querySelector('h3');
  previewHeading.id = 'sheetPreviewTitle';
  sheetDialog.setAttribute('aria-labelledby', previewHeading.id);
  const closeSheet = classButton('Закрыть', () => sheetDialog.close(), 'secondary');
  sheetDialog.append(closeSheet);
  document.body.append(sheetDialog);
  sheetDialog.addEventListener('close', () => previewSidebar.prepend(sheetPreview));
  sheetDialog.addEventListener('click', event => {
    if (event.target === sheetDialog) sheetDialog.close();
  });
  for (const anchor of [document.querySelector('.teacher-instructions'), document.querySelector('#step3 .print-summary')]) {
    const showSheet = classButton('Посмотреть макет A4', () => {
      sheetDialog.prepend(sheetPreview);
      sheetDialog.showModal();
    }, 'secondary');
    showSheet.classList.add('show-sheet-preview');
    showSheet.setAttribute('aria-haspopup', 'dialog');
    showSheet.prepend(listokIcon('layout'));
    anchor.before(showSheet);
  }
  const creationFooter = node('div', undefined, 'creation-footer');
  const variantLabel = $('setupVariants').closest('label');
  variantLabel.before(creationFooter);
  const variants = node('div', undefined, 'creation-variants'); variants.append(variantLabel);
  creationFooter.append(variants, $('recognizeBtn').closest('.actions'));
  $('recognizeBtn').textContent = 'Подготовить задания';
  $('recognizeBtn').append(listokIcon('arrowRight'));
  $('dropZone').querySelector('strong').textContent = 'Добавить фото или PDF';
  $('dropZone').querySelector('strong + span').textContent = 'Выберите файл или перетащите его сюда';
  $('inputTitle').textContent = 'Из чего создаём лист?';
  document.querySelector('#step1 .panel-heading p').textContent = 'Задания из учебника или ваши собственные.';

  // The print bundle has explicit purpose and a recognisable document icon.
  const fileCaptions = {
    downloadSheet: ['Открыть лист', 'Просмотр PDF'], saveSheetPdf: ['Скачать лист', 'Для печати ученикам'],
    downloadKeys: ['Ответы', 'Ключ для учителя'], downloadTeacher: ['Лист с ответами', 'Комплект учителя'],
    downloadAnswerForm: ['Бланк ответов', 'A4 · для быстрой проверки'], prepareAnswerForm: ['Создать бланк', 'A4 · только ответы'],
  };
  const fileIcons = {downloadSheet:'fileText', saveSheetPdf:'download', downloadKeys:'fileCheck', downloadTeacher:'library', downloadAnswerForm:'checklist', prepareAnswerForm:'filePlus'};
  for (const [id, [title, caption]] of Object.entries(fileCaptions)) {
    const link = $(id); if (!link) continue;
    const copy = node('span', undefined, 'file-action-copy');
    copy.append(node('strong', title), node('small', caption));
    link.replaceChildren(listokIcon(fileIcons[id]), copy);
  }
  for (const [id, icon] of Object.entries({batchNav:'checklist', analyticsNav:'chart', schoolNav:'school', studentNav:'graduationCap', studentInboxNav:'inbox'})) {
    const button=$(id); if(!button) continue;
    button.querySelector('svg')?.remove(); button.prepend(listokIcon(icon));
  }
  for (const [value,icon] of [['math','math'],['physics','atom'],['chemistry','flask'],['other','layers']]) {
    const label=document.querySelector(`[name="subject"][value="${value}"]`)?.closest('label');
    if(!label) continue;
    label.dataset.subject=value; label.querySelector('.subject-symbol').replaceChildren(listokIcon(icon));
  }
  document.querySelector('.upload-icon').replaceChildren(listokIcon('upload',{size:24}));
  document.querySelector('.brand-icon').replaceChildren(listokIcon('check',{size:24}));
  for(const [id,icon,title] of [
    ['takePhoto','camera'],['demoBtn','fileText'],['newSheetBtn','plus','Создать лист'],
    ['addTaskBtn','plus','Добавить задание'],['saveDraftBtn','save'],['saveCopyBtn','copy'],['saveBtn','save'],
    ['backToInput','arrowLeft','Материал'],['backToTasks','arrowLeft','Задания'],['editAgain','arrowLeft','Изменить лист'],
    ['toSettings','arrowRight','К оформлению'],['compileBtn','printer','Собрать PDF'],
    ['libraryBack','arrowLeft'],['cancelPublish','arrowLeft'],['shareFromSaved','share'],['copyPublication','copy'],
    ['scheduleResult','classes'],['feedbackSubmit','message'],['publishSubmit','share']
  ]) {
    const button=$(id); if(!button) continue;
    const text=title || button.textContent.trim().replace(/^[←＋+]\s*|\s*→$/g,'');
    button.replaceChildren(listokIcon(icon),node('span',text));
  }
  for(const [id,icon] of [['previousMonth','arrowLeft'],['nextMonth','arrowRight']]) {
    $(id).replaceChildren(listokIcon(icon)); $(id).classList.add('icon-only');
  }
  for(const [id,icon] of [['feedbackNav','star'],['demoEnter','play'],['demoExit','arrowLeft']]) {
    const button=$(id); if(!button) continue;
    const label=button.querySelector('span:last-child')?.textContent || button.textContent;
    button.replaceChildren(listokIcon(icon),node('span',label));
  }
  const newClass=document.querySelector('.class-create-disclosure > summary');
  newClass.replaceChildren(listokIcon('plus'),node('span','Новый класс'));
  // Accessible active-navigation state follows existing view changes.
  const syncNav = () => {
    for (const button of nav.querySelectorAll('.nav-button')) {
      if (button.classList.contains('active')) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
  };
  new MutationObserver(syncNav).observe(nav, {subtree: true, attributes: true, attributeFilter: ['class']});
  syncNav();
})();
