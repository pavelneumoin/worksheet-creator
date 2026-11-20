"use strict";
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/frontend/creation_controls.js'), 'utf8');

class Element {
  constructor(tag, className = '', text = '') {
    this.tagName = tag.toUpperCase(); this.className = className; this.textContent = text;
    this.children = []; this.events = {}; this.attrs = {}; this.dataset = {}; this.disabled = false;
    this.classList = {toggle() {}};
  }
  append(...children) {
    for (const child of children) { child.remove(); child.parentElement = this; this.children.push(child); }
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(item => item !== this);
    this.parentElement = null;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener(name, handler) { (this.events[name] ||= []).push(handler); }
  dispatchEvent(event) { for (const handler of this.events[event.type] || []) handler(event); }
  click() { if (!this.disabled) this.dispatchEvent({type:'click'}); }
  focus() { this.focused = true; }
  closest(selector) {
    let current = this;
    while (current) { if (selector === 'label' && current.tagName === 'LABEL') return current; current = current.parentElement; }
    return null;
  }
  querySelector(selector) {
    for (const child of this.children) {
      if (selector.startsWith('.') ? child.className.split(' ').includes(selector.slice(1)) : child.tagName.toLowerCase() === selector) return child;
      const nested = child.querySelector(selector); if (nested) return nested;
    }
    return null;
  }
}
function harness() {
  const synchronizers = [], observers = [];
  const element = (tag, className, text) => new Element(tag, className, text);
  const context = vm.createContext({
    synchronizers, element, queueMicrotask,
    Event: class { constructor(type) { this.type = type; } },
    MutationObserver: class { constructor(callback) { observers.push(callback); } observe() {} },
    section: title => element('section', '', title), miniature: () => element('span'),
  });
  const choices = source.slice(source.indexOf('  function choices('), source.indexOf('  function placement('));
  const template = source.slice(source.indexOf('  function templateSection('), source.indexOf('\n  const setup ='));
  vm.runInContext(choices + '\n' + template, context);
  return {context, synchronizers, observers, element};
}
function selectFixture(h, values = ['1','2'], value = '1') {
  const select = h.element('select'); select.id = 'columnsSelect'; select.value = value;
  select.options = values.map(item => ({value:item, disabled:false}));
  return select;
}

test('choosing placement preserves native events and updates the selected radio', () => {
  const h = harness(), select = selectFixture(h), events = [];
  for (const type of ['input','change']) select.addEventListener(type, () => events.push(type));
  const field = h.context.choices(select, 'Столбцы', [['1','Один'],['2','Два']], 'columns');
  const buttons = field.children.at(-1).children;
  buttons[1].click();
  assert.equal(select.value, '2');
  assert.deepEqual(events, ['input','change']);
  assert.equal(buttons[1].attrs['aria-checked'], 'true');
  assert.equal(buttons[0].tabIndex, -1);
  assert.equal(buttons[1].tabIndex, 0);
  buttons[1].click();
  assert.deepEqual(events, ['input','change']);
});

test('loading a saved sheet refreshes radios without changing native data or emitting edits', () => {
  const h = harness(), select = selectFixture(h, ['1','2','3','4','5','6'], '3');
  let edits = 0; select.addEventListener('change', () => edits++);
  const field = h.context.choices(select, 'Заданий', select.options.map(item => [item.value,item.value]), 'count');
  select.value = '5';
  h.synchronizers.forEach(sync => sync());
  const buttons = field.children.at(-1).children;
  assert.equal(buttons[4].attrs['aria-checked'], 'true');
  assert.equal(buttons[2].attrs['aria-checked'], 'false');
  assert.equal(buttons[4].tabIndex, 0);
  assert.equal(select.value, '5'); assert.equal(edits, 0);
});

test('disabled source fields cannot be changed through their visible controls', () => {
  const h = harness(), select = selectFixture(h);
  const field = h.context.choices(select, 'Столбцы', [['1','Один'],['2','Два']], 'columns');
  select.disabled = true; h.observers.forEach(sync => sync());
  const group = field.children.at(-1);
  group.children[1].click();
  assert.equal(select.value, '1');
  assert.equal(group.attrs['aria-disabled'], 'true');
  assert.ok(group.children.every(button => button.disabled && button.tabIndex === -1));
  select.disabled = false; h.observers.forEach(sync => sync());
  assert.equal(group.children[0].tabIndex, 0);
});

test('template keyboard navigation uses the original click action and hydrates saved choices', () => {
  const h = harness(), root = h.element('div'), picker = h.element('div','template-picker');
  const select = selectFixture(h, ['cards','list','guided','check'], 'cards'), label = h.element('label');
  label.append(select); root.append(picker,label);
  for (const value of select.options.map(item => item.value)) {
    const button = h.element('button'); button.dataset.template = value;
    button.append(h.element('span','template-thumb'),h.element('strong','',value),h.element('small','','Описание'));
    button.addEventListener('click', () => { select.value = value; h.synchronizers.forEach(sync => sync()); });
    picker.append(button);
  }
  h.context.templateSection(select,root); h.synchronizers.forEach(sync => sync());
  picker.children[0].dispatchEvent({type:'keydown',key:'End',preventDefault(){}});
  assert.equal(select.value, 'check');
  assert.equal(picker.children[3].attrs['aria-checked'], 'true');
  assert.equal(picker.children[3].focused, true);
  select.value = 'guided'; h.synchronizers.forEach(sync => sync());
  assert.equal(picker.children[2].attrs['aria-checked'], 'true');
  assert.equal(picker.children[3].attrs['aria-checked'], 'false');
});
