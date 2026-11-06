"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const script = fs.readFileSync(
  path.join(root, "app/frontend/script.js"),
  "utf8",
);
const requestSource = script.slice(
  script.indexOf("async function request("),
  script.indexOf("async function busy("),
);

function compilationHarness() {
  const fields = Object.fromEntries(Object.entries({
    teacherInput: "", gradeInput: "", columnsSelect: "1", countSelect: "3",
    templateSelect: "cards", variantInput: "", lessonDateInput: "", printSides: "single",
  }).map(([key, value]) => [key, {value}]));
  fields.reviewCheckbox = {checked: true};
  const state = {dirty: false, savedId: "material-1", revision: 2, result: {}, sheet: {
    teacher_name: "", grade: "", settings: {columns: 1, tasks_per_page: 3, field: "grid",
      template: "cards", print_sides: "single", variant: "", lesson_date: ""},
  }};
  const saves = [];
  const context = vm.createContext({
    state, $: (id) => fields[id], document: {querySelector: () => ({value: "grid"})},
    markDirty: (value) => {state.dirty = value;},
    saveCurrent: async () => {
      saves.push(JSON.parse(JSON.stringify(state.sheet)));
      state.revision += 1;
      state.dirty = false;
    },
  });
  vm.runInContext(script.slice(script.indexOf("function readSettings("), script.indexOf("function templateHint(")), context);
  return {context, fields, state, saves};
}

test("compile saves changed form values even when no blur/change event fired", async () => {
  const h = compilationHarness();
  h.fields.gradeInput.value = "8";
  h.fields.countSelect.value = "2";
  const payload = await h.context.prepareCompilation();
  assert.equal(h.saves.length, 1);
  assert.equal(h.saves[0].grade, "8");
  assert.equal(h.saves[0].settings.tasks_per_page, 2);
  assert.equal(payload.revision, 3);
  assert.equal(payload.reviewed, true);
  assert.deepEqual(JSON.parse(JSON.stringify(payload.worksheet)), h.saves[0]);
});

test("unchanged layout does not save merely because settings property order differs", async () => {
  const h = compilationHarness();
  const payload = await h.context.prepareCompilation();
  assert.equal(h.saves.length, 0);
  assert.equal(payload.revision, 2);
});

test("failed save prevents compilation from returning a stale snapshot", async () => {
  const h = compilationHarness();
  h.fields.gradeInput.value = "8";
  h.context.saveCurrent = async () => { throw new Error("revision conflict"); };
  await assert.rejects(h.context.prepareCompilation(), /revision conflict/);
  assert.equal(h.state.revision, 2);
});

function harness(fetch) {
  const timers = new Map();
  let timerId = 0;
  const context = vm.createContext({
    fetch,
    Headers,
    FormData,
    AbortController,
    TypeError,
    Error,
    state: { auth: { csrf_token: "test-csrf" } },
    setTimeout(fn, delay) {
      timers.set(++timerId, { fn, delay });
      return timerId;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  });
  vm.runInContext(requestSource, context);
  return { context, timers, request: context.request };
}
function untilAborted(signal) {
  return new Promise((resolve, reject) => {
    const abort = () =>
      reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
  });
}

test("timeout releases a pending request without claiming an HTTP rejection", async () => {
  const h = harness((url, options) => untilAborted(options.signal));
  const pending = h.request("/api/v2/jobs/report_pdf", { method: "POST" });
  assert.equal([...h.timers.values()][0].delay, 30000);
  [...h.timers.values()][0].fn();
  await assert.rejects(
    pending,
    (error) => /не ответил вовремя/.test(error.message) && !error.status,
  );
  assert.equal(h.timers.size, 0);
});

test("deadline includes response body reading and allows slower photo upload", async () => {
  let requestOptions;
  const h = harness(async (url, options) => {
    requestOptions = options;
    return { ok: true, json: () => untilAborted(options.signal) };
  });
  const pending = h.request("/submissions", {
    method: "POST",
    body: new FormData(),
  });
  await Promise.resolve();
  assert.equal([...h.timers.values()][0].delay, 120000);
  assert.equal(requestOptions.headers.get("X-CSRF-Token"), "test-csrf");
  assert.equal(requestOptions.credentials, "same-origin");
  [...h.timers.values()][0].fn();
  await assert.rejects(pending, /не ответил вовремя/);
  assert.equal(h.timers.size, 0);
});

test("caller cancellation still aborts the transport", async () => {
  const h = harness((url, options) => untilAborted(options.signal));
  const controller = new AbortController();
  const pending = h.request("/draft", { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, /не ответил вовремя/);
  assert.equal(h.timers.size, 0);
});

test("network failure is readable; definite HTTP errors retain their status", async () => {
  const offline = harness(async () => {
    throw new TypeError("Failed to fetch");
  });
  await assert.rejects(offline.request("/report"), /Нет связи с сервером/);
  assert.equal(offline.timers.size, 0);
  const rejected = harness(async () => ({
    ok: false,
    status: 409,
    json: async () => ({ error: "Версия изменена" }),
  }));
  await assert.rejects(
    rejected.request("/draft"),
    (error) => error.status === 409 && error.message === "Версия изменена",
  );
  assert.equal(rejected.timers.size, 0);
});

test("lost acceptance reply retries the same job key and original payload", async () => {
  const calls = [];
  let attempt = 0;
  const h = harness(async (url, options) => {
    calls.push({
      url,
      key: options.headers.get("Idempotency-Key"),
      body: options.body,
    });
    if (++attempt === 1)
      throw new TypeError("Lost reply after server accepted");
    return {
      ok: true,
      json: async () => ({ job: { id: "same-server-job", status: "queued" } }),
    };
  });
  Object.assign(h.context, {
    crypto: require("node:crypto").webcrypto,
    structuredClone,
    document: { addEventListener() {} },
    window: { addEventListener() {} },
    $: () => ({ scrollIntoView() {} }),
    notice() {},
  });
  vm.runInContext(
    fs.readFileSync(path.join(root, "app/frontend/jobs.js"), "utf8"),
    h.context,
  );
  vm.runInContext("renderJobs = () => {}; pollJobs = () => {};", h.context);
  await assert.rejects(
    vm.runInContext(
      "enqueueJob('report_pdf', {assignment_id:'original-assignment'})",
      h.context,
    ),
    /Нет связи/,
  );
  await assert.rejects(
    vm.runInContext(
      "enqueueJob('report_pdf', {assignment_id:'other-assignment'})",
      h.context,
    ),
    /Сначала повторите/,
  );
  await vm.runInContext("sendPendingJob()", h.context);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].key, calls[1].key);
  assert.equal(calls[0].body, calls[1].body);
  assert.match(calls[1].body, /original-assignment/);
  assert.equal(vm.runInContext("pendingSubmission", h.context), null);
  assert.equal(vm.runInContext("currentJobs.length", h.context), 1);
});
