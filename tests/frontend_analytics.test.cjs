"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../app/frontend/analytics.js"), "utf8");

function harness() {
  class Element {
    constructor(tag, text, classes) {
      this.tag = tag; this.textContent = text; this.className = classes || "";
      this.children = []; this.events = {}; this.attributes = {}; this.dataset = {}; this.style = {};
      this.value = ""; this.validationMessage = "";
    }
    append(...children) { this.children.push(...children); }
    prepend(...children) { this.children.unshift(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    addEventListener(name, handler) { this.events[name] = handler; }
    setCustomValidity(message) { this.validationMessage = message; }
    reportValidity() { return !all(this).some(el => el.validationMessage); }
  }
  function all(root) { return [root, ...root.children.flatMap(all)]; }
  const views = {}, calls = [], work = [], navigation = [], notes = [];
  const context = vm.createContext({
    URLSearchParams, Node: Element, state: {auth: {authenticated: true}},
    node: (...args) => new Element(...args), studioIcon: () => new Element("svg"),
    document: {querySelector: () => new Element("div")},
    $: id => views[id] ||= new Element("section"),
    Option: function(text, value) { const el = new Element("option", text); el.value = value; return el; },
    classButton: (text, action, kind) => { const el = new Element("button", text, kind); el.events.click = action; return el; },
    batchHeading: title => new Element("h1", title),
    busy: (_, action) => { const pending = action(); work.push(pending); return pending; },
    request: async (url, options) => { calls.push([url, options]); return {report: context.report}; },
    showView: name => navigation.push(name), notice: text => notes.push(text),
    subjectLabel: value => value, classJson: (method, body) => ({method, body: JSON.stringify(body)}),
  });
  vm.runInContext(source, context);
  context.report = {
    scope: "school", title: "Тестовая школа", filters: {scope: "school"},
    available_classes: [{id: "class-1", name: "8А"}], available_blocks: [], teachers: [],
    totals: {percent: null, confirmed: 0, expected: 0, coverage: 0, needs_review: 0, classes: 0, assignments: 0},
    works: [], topics: [], classes: [],
  };
  return {context, all, calls, work, navigation, notes, views};
}

test("report filtering preserves school scope and omits blank fields", async () => {
  const h = harness(), view = h.context.analyticsFilters(h.context.report, {scope: "school"});
  const form = h.all(view).find(el => el.tag === "form");
  const controls = Object.fromEntries(h.all(form).filter(el => el.name).map(el => [el.name, el]));
  controls.class_id.value = "class-1";
  controls.q.value = "  Уравнения  ";
  controls.from_date.value = "2026-11-01";
  form.events.submit({preventDefault() {}});
  await h.work.at(-1);
  const query = new URLSearchParams(h.calls[0][0].split("?")[1]);
  assert.equal(query.get("scope"), "school");
  assert.equal(query.get("class_id"), "class-1");
  assert.equal(query.get("q"), "Уравнения");
  assert.equal(query.has("to_date"), false);
  assert.equal(query.has("teacher_id"), false);
});

test("an inverted date range never requests or replaces a report", async () => {
  const h = harness(), view = h.context.analyticsFilters(h.context.report, {scope: "school"});
  const form = h.all(view).find(el => el.tag === "form");
  const inputs = Object.fromEntries(h.all(form).filter(el => el.name).map(el => [el.name, el]));
  inputs.from_date.value = "2026-11-20";
  inputs.to_date.value = "2026-11-01";
  form.events.submit({preventDefault() {}});
  assert.match(inputs.to_date.validationMessage, /не раньше/);
  assert.equal(h.calls.length, 0);
  assert.equal(h.navigation.length, 0);
  inputs.to_date.value = "2026-11-30";
  inputs.to_date.events.input();
  assert.equal(inputs.to_date.validationMessage, "");
  form.events.submit({preventDefault() {}});
  await h.work.at(-1);
  assert.equal(h.calls.length, 1);
});

test("reset removes filters without changing the school report scope", async () => {
  const h = harness(), view = h.context.analyticsFilters(h.context.report, {scope: "school", class_id: "class-1", q: "Тема"});
  await h.all(view).find(el => el.textContent === "Сбросить всё").events.click();
  assert.equal(h.calls[0][0], "/api/v2/analytics?scope=school");
});

test("a missing result stays distinct from a confirmed zero", () => {
  const {context} = harness();
  assert.equal(context.percentage(null), "—");
  assert.equal(context.percentage(0), "0%");
  assert.equal(context.analyticsTone(undefined), "neutral");
  assert.equal(context.analyticsTone(null), "neutral");
  assert.equal(context.analyticsTone(0), "low");
});

test("mobile report cells retain header labels and table semantics", () => {
  const h = harness(), view = h.context.analyticsTable(["Класс", "Проверено"], [["8А", "2 из 30"]], "Работы");
  const cells = h.all(view).filter(el => el.tag === "td");
  assert.deepEqual(cells.map(el => el.dataset.label), ["Класс", "Проверено"]);
  assert.equal(h.all(view).find(el => el.tag === "table").attributes.role, "table");
  assert.ok(cells.every(el => el.attributes.role === "cell"));
});

test("opening reports requires MAX authentication before requesting data", async () => {
  const h = harness(); h.context.state.auth.authenticated = false;
  await h.context.openAnalytics();
  await h.context.openSchool();
  assert.equal(h.calls.length, 0);
  assert.equal(h.notes.length, 2);
});
