"use strict";
// The original fields remain the source of truth for saved sheets and API requests.
(() => {
  const byId = id => document.getElementById(id);
  const required = ['setupTemplate', 'setupField', 'setupColumns', 'setupCount', 'setupHeight', 'templateSelect', 'columnsSelect', 'countSelect', 'fieldHeight'];
  if (required.some(id => !byId(id)) || document.querySelector('.creation-settings-body')) return;
  const element = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text) el.textContent = text;
    return el;
  };
  const synchronizers = [];
  const fieldOptions = [
    ['grid', 'В клетку', 'Вычисления и графики'],
    ['blank', 'Без клеток', 'Схемы и решения'],
    ['none', 'Только задания', 'Ответы в тетради'],
  ];
  function section(title, className = '') {
    const el = element('section', `creation-section ${className}`);
    el.append(element('h3', 'creation-section-title', title));
    return el;
  }
  function miniature(kind) {
    const preview = element('span', `creation-miniature creation-miniature--${kind}`);
    preview.setAttribute('aria-hidden', 'true');
    preview.append(element('i'), element('i'), element('i'));
    return preview;
  }
  function choices(select, title, options, kind) {
    const field = element('div', `creation-field creation-field--${kind}`);
    const heading = element('span', 'creation-field-title', title);
    heading.id = `${select.id}ChoicesTitle`;
    const group = element('div', `creation-choices creation-choices--${kind}`);
    group.setAttribute('role', 'radiogroup');
    group.setAttribute('aria-labelledby', heading.id);
    const buttons = options.map(([value, label, description]) => {
      const button = element('button', 'creation-choice');
      button.type = 'button';
      button.dataset.value = value;
      button.setAttribute('role', 'radio');
      if (kind === 'columns') button.append(miniature(`columns-${value}`));
      if (kind === 'field') button.append(miniature(value));
      const copy = element('span', 'creation-choice-copy');
      copy.append(element('strong', '', label));
      if (description) copy.append(element('small', '', description));
      button.append(copy);
      button.addEventListener('click', () => choose(value));
      button.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const enabled = buttons.filter(item => !item.disabled);
        const index = enabled.indexOf(button);
        const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? enabled.length - 1
          : (index + (event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1) + enabled.length) % enabled.length;
        const next = enabled[nextIndex];
        if (next) { choose(next.dataset.value); next.focus(); }
      });
      group.append(button);
      return button;
    });
    function sync() {
      group.setAttribute('aria-disabled', String(select.disabled));
      field.classList.toggle('is-disabled', select.disabled);
      for (const button of buttons) {
        const option = [...select.options].find(item => item.value === button.dataset.value);
        button.disabled = select.disabled || !option || option.disabled;
        const selected = button.dataset.value === select.value;
        button.setAttribute('aria-checked', String(selected));
        button.tabIndex = selected && !button.disabled ? 0 : -1;
      }
    }
    function choose(value) {
      if (select.disabled || buttons.find(button => button.dataset.value === value)?.disabled) return;
      if (select.value !== value) {
        select.value = value;
        select.dispatchEvent(new Event('input', {bubbles: true}));
        select.dispatchEvent(new Event('change', {bubbles: true}));
      }
      sync();
    }
    field.append(heading, select, group);
    select.hidden = true;
    select.addEventListener('change', sync);
    select.form?.addEventListener('reset', () => queueMicrotask(sync));
    new MutationObserver(sync).observe(select, {attributes: true, attributeFilter: ['disabled']});
    synchronizers.push(sync);
    sync();
    return field;
  }
  function placement(columns, count, height) {
    const group = section('Размещение на странице', 'creation-section--placement');
    const row = element('div', 'creation-placement-grid');
    row.append(
      choices(columns, 'Столбцы', [['1', 'Один'], ['2', 'Два']], 'columns'),
      choices(count, 'Заданий на странице', ['1', '2', '3', '4', '5', '6'].map(value => [value, value]), 'count'),
    );
    const heightLabel = height.closest('label');
    heightLabel.classList.add('creation-height');
    const note = element('span', 'creation-field-note', 'При выборе «Только задания» поле для решения не печатается.');
    note.id = `${height.id}Explanation`;
    height.setAttribute('aria-describedby', note.id);
    heightLabel.append(note);
    group.append(row, heightLabel);
    synchronizers.push(() => {
      heightLabel.classList.toggle('is-disabled', height.disabled);
      note.hidden = !height.disabled;
    });
    return group;
  }
  function templateSection(select, root) {
    const picker = root.querySelector('.template-picker');
    if (!picker) return null;
    const group = section('Шаблон листа', 'creation-section--templates');
    const oldLabel = select.closest('label');
    group.append(picker, select);
    select.hidden = true;
    oldLabel?.remove();
    picker.setAttribute('role', 'radiogroup');
    for (const button of picker.children) {
      button.setAttribute('role', 'radio');
      const title = button.querySelector('strong');
      const description = button.querySelector('small');
      const copy = element('span', 'creation-template-copy');
      copy.append(title, description);
      button.append(copy);
      button.querySelector('.template-thumb')?.setAttribute('aria-hidden', 'true');
      button.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const buttons = [...picker.children].filter(item => !item.disabled);
        const index = buttons.indexOf(button);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
          : (index + (event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
        if (buttons[next]) { buttons[next].click(); buttons[next].focus(); }
      });
    }
    synchronizers.push(() => {
      for (const button of picker.children) {
        const selected = button.dataset.template === select.value;
        button.setAttribute('aria-checked', String(selected));
        button.tabIndex = selected && !button.disabled ? 0 : -1;
      }
    });
    return group;
  }

  const setup = document.querySelector('.setup-settings');
  const setupBody = element('div', 'creation-settings-body');
  const setupOldGrid = byId('setupColumns').closest('.form-grid');
  const setupTemplate = templateSection(byId('setupTemplate'), setup);
  const setupField = section('Место для решения', 'creation-section--field');
  setupField.append(choices(byId('setupField'), 'Формат поля', fieldOptions, 'field'));
  setupBody.append(setupTemplate, setupField, placement(byId('setupColumns'), byId('setupCount'), byId('setupHeight')));
  setupOldGrid.remove();
  byId('setupHint').hidden = true;
  setup.querySelector('summary').after(setupBody);

  const step = byId('step3');
  const stepOldGrid = byId('columnsSelect').closest('.form-grid');
  const stepTemplate = templateSection(byId('templateSelect'), step);
  const stepField = step.querySelector('.layout-options').closest('fieldset');
  stepField.classList.add('creation-section', 'creation-section--field');
  const fieldLabels = stepField.querySelectorAll('.layout-options > label');
  for (const label of fieldLabels) {
    const input = label.querySelector('input');
    const [, title, description] = fieldOptions.find(([value]) => input.value === value);
    label.querySelector('strong').textContent = title;
    label.querySelector('small').textContent = description;
    label.querySelector('.layout-icon').replaceWith(miniature(input.value));
    const copy = element('span', 'creation-choice-copy');
    copy.append(label.querySelector('strong'), label.querySelector('small'));
    label.append(copy);
  }
  const stepBody = element('div', 'creation-settings-body');
  byId('templateHint').before(stepBody);
  stepBody.append(stepTemplate, stepField, placement(byId('columnsSelect'), byId('countSelect'), byId('fieldHeight')));
  stepOldGrid.remove();
  byId('templateHint').hidden = true;

  const syncAll = () => synchronizers.forEach(sync => sync());
  document.addEventListener('listok:settingschange', syncAll);
  byId('workspace').addEventListener('change', syncAll);
  // Covers native field hydration and reset while changing editor steps.
  for (const id of ['step1', 'step3']) new MutationObserver(syncAll).observe(byId(id), {attributes: true, attributeFilter: ['hidden']});
  syncAll();
})();
