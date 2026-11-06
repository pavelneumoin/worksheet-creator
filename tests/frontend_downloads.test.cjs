const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app/frontend/downloads.js'), 'utf8');

function setup() {
  const calls = [], notices = [], pending = [];
  let now = 100000;
  const context = vm.createContext({
    state: {auth: {user: {kind: 'max'}, csrf_token: 'session-a'}},
    window: {WebApp: {downloadFile: (...args) => { calls.push(args); return Promise.resolve({status: 'downloading'}); }}},
    request: () => new Promise((resolve, reject) => pending.push({resolve, reject})),
    notice: (...args) => notices.push(args),
    busy: (text, work) => work().catch(e => notices.push([e.message, true])),
    location: {origin: 'https://listok.test'}, URL,
    Date: {now: () => now},
  });
  vm.runInContext(source, context);
  return {context, calls, notices, pending, advance: ms => now += ms,
    bind: (id = 'one') => { const a = {}; context.bindArtifactDownload(a, id, 'pdf_url', 'Лист.pdf'); return a; },
    resolve: () => pending.shift().resolve({pdf_url:'/api/v2/downloads/ticket/file.pdf', expires_at: (now + 600000) / 1000}),
  };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const click = a => a.onclick({preventDefault() {}});

test('MAX download runs synchronously inside click; tickets shared for one artifact', async () => {
  const h = setup(), a = h.bind(), b = h.bind();
  assert.equal(h.pending.length, 1);
  h.resolve(); await settle(); click(a);
  assert.equal(h.calls.length, 1); // before any microtask/network await
  assert.equal(h.calls[0][0], 'https://listok.test/api/v2/downloads/ticket/file.pdf');
  click(b); assert.equal(h.calls.length, 2);
});
test('expired ticket requires a fresh click after refresh', async () => {
  const h = setup(), a = h.bind(); h.resolve(); await settle();
  h.advance(601000); click(a);
  assert.equal(h.calls.length, 0);
  h.resolve(); await settle();
  assert.equal(h.calls.length, 0);
  assert.match(h.notices[0][0], /ещё раз/);
  click(a); assert.equal(h.calls.length, 1);
});
test('failed prefetch retries and does not lose the download button', async () => {
  const h = setup(), a = h.bind();
  h.pending.shift().reject(new Error('offline')); await settle(); click(a);
  assert.equal(h.pending.length, 1);
  h.resolve(); await settle(); click(a); assert.equal(h.calls.length, 1);
});
test('a different session never reuses the previous download ticket', async () => {
  const h = setup(), a = h.bind(); h.resolve(); await settle();
  h.context.state.auth.csrf_token = 'session-b'; click(a);
  assert.equal(h.calls.length, 0); assert.equal(h.pending.length, 1);
  h.resolve(); await settle();
});
test('browser profile uses normal links even if MAX Bridge is present', () => {
  const h = setup(); h.context.state.auth.user.kind = 'local';
  assert.equal(h.bind().onclick, null); assert.equal(h.pending.length, 0);
});
test('native cancellation and synchronous failures produce readable messages', async () => {
  const h = setup(), a = h.bind(); h.resolve(); await settle();
  h.context.window.WebApp.downloadFile = () => { throw new Error('native'); };
  click(a); assert.match(h.notices[0][0], /не смог скачать/);
  h.context.window.WebApp.downloadFile = () => Promise.resolve({status: 'cancelled'});
  click(a); await settle(); assert.match(h.notices[1][0], /отменено/);
});
