'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { startServer, tempFile } = require('./helpers');

const KEY = 'ade-geheim';
let srv;

before(async () => { srv = await startServer({ key: KEY }); });
after(async () => { await srv.stop(); });

const api = (path, options = {}) => fetch(srv.url + path, {
  ...options,
  headers: { 'X-Group-Key': encodeURIComponent(KEY), 'Content-Type': 'application/json', ...options.headers },
});
const push = records => api('/api/push', { method: 'POST', body: JSON.stringify({ records }) });
const member = (id, u, name) => ({ col: 'members', rec: { id, u, name, paypal: '', order: 1 } });

test('ohne oder mit falschem Zugangscode gibt es 401', async () => {
  for (const headers of [{ 'X-Group-Key': '' }, { 'X-Group-Key': 'falsch' }]) {
    const res = await fetch(srv.url + '/api/state', { headers });
    assert.equal(res.status, 401);
    assert.equal((await res.json()).ade, 1);
  }
});

test('neuere Version gewinnt, ältere wird ignoriert', async () => {
  let body = await (await push([member('p1', 100, 'Alex')])).json();
  assert.equal(body.members.p1.name, 'Alex');
  const rev = body.rev;

  body = await (await push([member('p1', 50, 'Alt')])).json();
  assert.equal(body.members.p1.name, 'Alex');
  assert.equal(body.rev, rev, 'nichts geändert, also keine neue Revision');

  body = await (await push([member('p1', 200, 'Alexandra')])).json();
  assert.equal(body.members.p1.name, 'Alexandra');
  assert.equal(body.rev, rev + 1);

  const unchanged = await (await api('/api/state?since=' + body.rev)).json();
  assert.deepEqual(unchanged, { ade: 1, rev: body.rev, unchanged: true });
});

test('ungültige Datensätze werden verworfen', async () => {
  const body = await (await push([
    { col: 'members', rec: { id: '__proto__', u: 5, name: 'x' } },
    { col: 'members', rec: { id: 'constructor', u: 5, name: 'ok' } },
    { col: 'members', rec: { id: 'ohne-zeit', name: 'x' } },
    { col: 'members', rec: { id: 'p9', u: 0, name: 'x' } },
    { col: 'members', rec: { id: 'gross', u: 5, name: 'x'.repeat(5000) } },
    { col: 'hacker', rec: { id: 'p8', u: 5 } },
    'quatsch',
  ])).json();
  assert.deepEqual(Object.keys(body.members).sort(), ['constructor', 'p1']);
});

test('kaputte Anfragen', async () => {
  assert.equal((await api('/api/push', { method: 'POST', body: '{nein' })).status, 400);
  assert.equal((await api('/api/push', { method: 'POST', body: JSON.stringify({}) })).status, 400);
  assert.equal((await api('/api/state', { method: 'DELETE' })).status, 405);
  assert.equal((await api('/api/gibtsnicht')).status, 404);
  const big = await api('/api/push', { method: 'POST', body: 'x'.repeat(1_100_000) }).catch(err => err);
  assert.ok(big instanceof Error || big.status === 413);
});

test('liefert die App auch unter einem Unterpfad aus', async () => {
  const redirect = await fetch(srv.url + '/ade', { redirect: 'manual' });
  assert.equal(redirect.status, 301);
  assert.equal(redirect.headers.get('location'), '/ade/');

  const page = await fetch(srv.url + '/ade/');
  assert.equal(page.status, 200);
  assert.match(page.headers.get('content-type'), /text\/html/);
  assert.match(page.headers.get('x-robots-tag'), /noindex/);
  assert.match(await page.text(), /<title>ADE 2026/);

  for (const p of ['/ade/api/state', '//api/state']) {
    const res = await api(p);
    assert.equal(res.status, 200, p);
    assert.equal((await res.json()).ade, 1);
  }
});

test('Daten überstehen einen Neustart', async () => {
  const dataFile = tempFile();
  let s = await startServer({ key: KEY, dataFile });
  await fetch(s.url + '/api/push', {
    method: 'POST',
    headers: { 'X-Group-Key': KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ records: [member('p2', 300, 'Ben')] }),
  });
  await s.stop();
  s = await startServer({ key: KEY, dataFile });
  const body = await (await fetch(s.url + '/api/state', { headers: { 'X-Group-Key': KEY } })).json();
  await s.stop();
  assert.equal(body.members.p2.name, 'Ben');
  assert.equal(body.rev, 1);
});

test('kaputte Datendatei wird beiseitegelegt statt überschrieben', async () => {
  const dataFile = tempFile();
  fs.writeFileSync(dataFile, '{kaputt');
  const s = await startServer({ key: KEY, dataFile });
  await s.stop();
  const backups = fs.readdirSync(require('node:path').dirname(dataFile)).filter(f => f.includes('kaputt-'));
  assert.equal(backups.length, 1);
});

test('Sonderzeichen im Zugangscode', async () => {
  const s = await startServer({ key: 'Früh stück €' });
  const ok = await fetch(s.url + '/api/state', { headers: { 'X-Group-Key': encodeURIComponent('Früh stück €') } });
  await s.stop();
  assert.equal(ok.status, 200);
});
