'use strict';
// Browser-Tests mit Playwright (npm i -D playwright, dann: node --test tests/)
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { INDEX_URL, startServer, loadPlaywright, tempFile } = require('./helpers');

const pw = loadPlaywright();
const skip = pw ? false : 'Playwright ist nicht installiert';
let browser;

before(async () => { if (pw) browser = await pw.chromium.launch(); });
after(async () => { if (browser) await browser.close(); });

async function open(url = INDEX_URL) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'de-DE', timezoneId: 'Europe/Berlin' });
  // Teilen-Menü abfangen, damit der Test den Link lesen kann
  await context.addInitScript(() => { navigator.share = async data => { window.__shared = data; }; });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  page.on('dialog', dialog => dialog.accept());
  await page.goto(url);
  return { page, context, errors };
}

const balances = page => page.evaluate(() => {
  const s = ADE.summarize(ADE.state);
  const out = {};
  for (const [id, v] of Object.entries(s.bal)) out[ADE.state.members[id].name] = v;
  return out;
});

const waitMode = (page, mode) => page.waitForFunction(m => ADE.sync.mode === m, mode, { timeout: 15000 });

async function setNames(page, names) {
  const inputs = page.locator('.setup-grid input');
  for (let i = 0; i < names.length; i++) await inputs.nth(i).fill(names[i]);
  await page.getByRole('button', { name: 'Los geht’s' }).click();
}

async function addExpense(page, o) {
  await page.locator('#fab').click();
  const d = page.locator('#expenseDialog');
  await d.locator('.amount-input').fill(o.amount);
  await d.getByLabel('Beschreibung').fill(o.title);
  if (o.multi) {
    await d.locator('.pay-section .chip', { hasText: 'Mehrere' }).click();
    for (const [name, v] of Object.entries(o.multi)) await d.getByLabel('Bezahlt von ' + name).fill(v);
  } else if (o.payer) {
    await d.locator('.pay-section .chip', { hasText: o.payer }).click();
  }
  for (const name of o.without || []) await d.locator('.split-section .check-row', { hasText: name }).click();
  if (o.shares) {
    await d.locator('.split-section .seg button', { hasText: 'Anteile' }).click();
    for (const [name, n] of Object.entries(o.shares)) {
      for (let i = 1; i < n; i++) await d.getByLabel('Mehr Anteile für ' + name).click();
      if (n === 0) await d.getByLabel('Weniger Anteile für ' + name).click();
    }
  }
  if (o.exact) {
    await d.locator('.split-section .seg button', { hasText: 'Beträge' }).click();
    for (const [name, v] of Object.entries(o.exact)) await d.getByLabel('Anteil von ' + name).fill(v);
  }
  await d.getByRole('button', { name: 'Eintragen' }).click();
  await d.waitFor({ state: 'hidden' });
}

async function sharedLink(page, button) {
  await page.evaluate(() => { window.__shared = null; });
  await button.click();
  await page.waitForFunction(() => window.__shared);
  const text = await page.evaluate(() => window.__shared.text);
  return /(\S+#g=\S+)/.exec(text)[1];
}

test('Beträge werden richtig gelesen', { skip }, async () => {
  const { page, context } = await open();
  const cases = {
    '12': 1200, '12,5': 1250, '12.50': 1250, '1.234,56': 123456, '1,234.56': 123456, '1.234': 123400,
    ',5': 50, '12,': 1200, '12 €': 1200, '10+2,50': 1250, '12,345': null, 'abc': null, '': null, '1.2.3': null, '-5': null,
  };
  const parsed = await page.evaluate(c => Object.fromEntries(Object.keys(c).map(k => [k, ADE.parseAmount(k)])), cases);
  assert.deepEqual(parsed, cases);
  await context.close();
});

test('Aufteilung ist centgenau und der Extra-Cent wandert', { skip }, async () => {
  const { page, context } = await open();
  const r = await page.evaluate(() => {
    const equal = ADE.shareOf({ id: 'a1', amount: 1000, split: { mode: 'equal', values: { p1: 1, p2: 1, p3: 1 } } });
    const shares = ADE.shareOf({ id: 'a2', amount: 6400, split: { mode: 'shares', values: { p1: 2, p2: 1, p3: 1 } } });
    const extra = { p1: 0, p2: 0, p3: 0 };
    for (let i = 0; i < 300; i++) {
      const s = ADE.shareOf({ id: 'x' + i, amount: 100, split: { mode: 'equal', values: { p1: 1, p2: 1, p3: 1 } } });
      for (const k in s) if (s[k] === 34) extra[k]++;
    }
    return { equal: Object.values(equal).sort(), shares: { ...shares }, extra };
  });
  assert.deepEqual(r.equal, [333, 333, 334]);
  assert.deepEqual(r.shares, { p1: 3200, p2: 1600, p3: 1600 });
  for (const n of Object.values(r.extra)) assert.ok(n > 50, 'jeder bekommt mal den Extra-Cent');
  await context.close();
});

test('Wer zahlt wem: höchstens n−1 Überweisungen, danach sind alle quitt', { skip }, async () => {
  const { page, context } = await open();
  const runs = await page.evaluate(() => {
    const out = [];
    for (let run = 0; run < 300; run++) {
      const n = 2 + (run % 6);
      const bal = {};
      let total = 0;
      for (let i = 1; i < n; i++) { bal['p' + i] = Math.round((Math.random() - 0.5) * 100000); total += bal['p' + i]; }
      bal['p' + n] = -total;
      const transfers = ADE.settle(bal);
      for (const t of transfers) { bal[t.from] += t.amount; bal[t.to] -= t.amount; }
      out.push({ n, count: transfers.length, square: Object.values(bal).every(v => v === 0), positive: transfers.every(t => t.amount > 0) });
    }
    return out;
  });
  for (const r of runs) {
    assert.ok(r.square && r.positive);
    assert.ok(r.count <= r.n - 1);
  }
  await context.close();
});

test('Datensätze aus Links werden streng geprüft', { skip }, async () => {
  const { page, context } = await open();
  const r = await page.evaluate(() => {
    const ok = { id: 'e1', u: 5, kind: 'expense', amount: 1000, date: '2026-10-24', title: 'Pizza', category: 'food', paidBy: { p1: 1000 }, split: { mode: 'equal', values: { p1: 1, p2: 1 } } };
    const bad = [
      { ...ok, amount: 0 },
      { ...ok, amount: 1.5 },
      { ...ok, paidBy: { p1: 900 } },
      { ...ok, split: { mode: 'exact', values: { p1: 100, p2: 100 } } },
      { ...ok, split: { mode: 'equal', values: {} } },
      { ...ok, split: { mode: 'magic', values: { p1: 1 } } },
      { ...ok, id: '__proto__' },
      { ...ok, date: 'morgen' },
      { id: 'z1', u: 5, kind: 'payment', from: 'p1', to: 'p1', amount: 100, date: '2026-10-24' },
    ];
    return {
      ok: !!ADE.sanitize('items', ok),
      title: ADE.sanitize('items', { ...ok, title: '<img src=x onerror=alert(1)>' }).title,
      bad: bad.map(b => ADE.sanitize('items', b)),
    };
  });
  assert.equal(r.ok, true);
  assert.equal(r.title, '<img src=x onerror=alert(1)>', 'Text bleibt Text (wird nur als Text angezeigt)');
  assert.deepEqual(r.bad, r.bad.map(() => null));
  await context.close();
});

test('Präparierte Links schleusen keinen Code ein', { skip }, async () => {
  const sender = await open();
  const link = await sender.page.evaluate(async () => {
    const evil = '<img src=x onerror="window.__pwned=1">';
    const s = ADE.sanitizeState({
      meta: [{ id: 'group', u: 9, name: evil, place: evil }],
      members: [{ id: 'p1', u: 9, name: evil, paypal: 'javascript:alert(1)', order: 1 }],
      items: [{ id: 'e1', u: 9, kind: 'expense', amount: 500, date: '2026-10-24', title: evil, category: 'food', paidBy: { p1: 500 }, split: { mode: 'equal', values: { p1: 1, p2: 1 } } }],
    });
    return location.href.split('#')[0] + '#g=' + await ADE.encodeState(s);
  });
  const { page, context, errors } = await open(link);
  await page.waitForFunction(() => Object.keys(ADE.state.items).length === 1);
  for (const name of ['Ausgaben', 'Gruppe', 'Übersicht']) await page.getByRole('button', { name, exact: true }).click();
  assert.equal(await page.evaluate(() => window.__pwned), undefined);
  assert.equal(await page.locator('img').count(), 0);
  assert.match(await page.locator('#title').innerText(), /^<img src=x/);
  assert.equal(await page.evaluate(() => ADE.state.members.p1.paypal), '');
  assert.deepEqual(errors, []);
  await sender.context.close();
  await context.close();
});

test('Durchlauf lokal: Namen, Ausgaben, Abrechnung und Abgleich per Link', { skip }, async () => {
  const alex = await open();
  const { page } = alex;
  await setNames(page, ['Alex', 'Ben', 'Chris', 'Dana']);
  await page.locator('.chip', { hasText: 'Alex' }).click();

  await addExpense(page, { amount: '600', title: 'Airbnb', payer: 'Alex' });
  await addExpense(page, { amount: '340', title: 'Tickets ADE', payer: 'Ben' });
  await addExpense(page, { amount: '23,40', title: 'Uber', payer: 'Chris', without: ['Ben'] });
  await addExpense(page, { amount: '64', title: 'Drinks', payer: 'Dana', shares: { Alex: 2, Ben: 1, Chris: 1, Dana: 0 } });
  await addExpense(page, { amount: '120', title: 'Dinner', multi: { Alex: '70', Ben: '50' }, exact: { Alex: '30', Ben: '30', Chris: '30', Dana: '30' } });

  assert.deepEqual(await balances(page), { Alex: 36520, Ben: 10900, Chris: -26540, Dana: -20880 });
  const categories = await page.evaluate(() => ({ ...ADE.summarize(ADE.state).byCat }));
  assert.deepEqual(categories, { stay: 60000, tickets: 34000, transit: 2340, drinks: 6400, food: 12000 });

  const transfers = page.locator('.transfer');
  await assert.doesNotReject(transfers.first().waitFor());
  assert.equal(await transfers.count(), 3);
  assert.match(await transfers.first().innerText(), /Chris[\s\S]*Alex[\s\S]*265,40/);
  assert.match(await page.locator('.me-line').innerText(), /bekommst noch 365,20/);

  // Rückzahlung über „Bezahlt? Eintragen“
  await transfers.first().getByRole('button', { name: 'Bezahlt' }).click();
  await page.locator('#paymentDialog').getByRole('button', { name: 'Speichern' }).click();
  await page.locator('#paymentDialog').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('.transfer').count(), 2);
  assert.match(await page.locator('.me-line').innerText(), /bekommst noch 99,80/);

  // Stand teilen und auf einem zweiten „Handy“ öffnen
  const link = await sharedLink(page, page.locator('.banner button'));
  assert.equal(await page.locator('.banner').count(), 0, 'Hinweis verschwindet nach dem Teilen');
  const ben = await open(link);
  await ben.page.waitForFunction(() => Object.keys(ADE.state.items).length === 6);
  const fp = page => page.evaluate(() => ADE.fingerprint(ADE.state));
  assert.equal(await fp(ben.page), await fp(page));
  assert.deepEqual(await balances(ben.page), await balances(page));
  assert.ok(!(await ben.page.evaluate(() => location.hash)), 'Link-Daten verschwinden aus der Adresszeile');

  // Ben trägt etwas ein, Alex löscht gleichzeitig etwas – beides kommt beim anderen an
  await ben.page.locator('.chip', { hasText: 'Ben' }).click();
  await addExpense(ben.page, { amount: '18', title: 'Frühstück', payer: 'Ben' });
  await page.getByRole('button', { name: 'Ausgaben' }).click();
  await page.locator('.row', { hasText: 'Uber' }).click();
  await page.locator('#expenseDialog').getByRole('button', { name: 'Löschen' }).click();
  await page.locator('#expenseDialog').waitFor({ state: 'hidden' });

  const benLink = await sharedLink(ben.page, ben.page.locator('.banner button'));
  const alexLink = await sharedLink(page, page.locator('.banner button'));
  await page.goto(benLink);
  await ben.page.goto(alexLink);
  for (const p of [page, ben.page]) await p.waitForFunction(() => Object.values(ADE.state.items).filter(i => !i.deleted).length === 6);
  assert.equal(await fp(ben.page), await fp(page));
  assert.deepEqual(await balances(page), await balances(ben.page));
  assert.deepEqual(await page.evaluate(() => Object.values(ADE.state.items).filter(i => !i.deleted).map(i => i.title || 'Zahlung').sort()),
    ['Airbnb', 'Dinner', 'Drinks', 'Frühstück', 'Tickets ADE', 'Zahlung']);

  // Bearbeiten
  await page.getByRole('button', { name: 'Ausgaben' }).click();
  await page.locator('.row', { hasText: 'Drinks' }).click();
  await page.locator('#expenseDialog .amount-input').fill('80');
  await page.locator('#expenseDialog').getByRole('button', { name: 'Speichern' }).click();
  assert.match(await page.locator('.row', { hasText: 'Drinks' }).innerText(), /80,00/);

  assert.deepEqual([...alex.errors, ...ben.errors], []);
  await alex.context.close();
  await ben.context.close();
});

test('Gruppe: umbenennen, PayPal, Person hinzufügen', { skip }, async () => {
  const { page, context, errors } = await open();
  await setNames(page, ['Alex', 'Ben', 'Chris', 'Dana']);
  await page.locator('.chip', { hasText: 'Ben' }).click();
  await addExpense(page, { amount: '100', title: 'Taxi', payer: 'Alex' });
  await page.getByRole('button', { name: 'Gruppe' }).click();
  await page.getByLabel('PayPal.me-Name von Alex').fill('https://paypal.me/alex.test');
  await page.getByLabel('PayPal.me-Name von Alex').press('Tab');
  await page.getByRole('button', { name: 'Person hinzufügen' }).click();
  await page.keyboard.type('Eli');
  await page.keyboard.press('Tab');
  await page.getByRole('button', { name: 'Übersicht' }).click();
  const paypal = page.getByRole('link', { name: 'PayPal' }).first();
  assert.equal(await paypal.getAttribute('href'), 'https://paypal.me/alex.test/25.00EUR');
  assert.match(await page.locator('#subtitle').innerText(), /5 Leute/);
  assert.deepEqual(errors, []);
  await context.close();
});

test('Live-Abgleich über server.js, auch nach Verbindungsabbruch', { skip }, async () => {
  const dataFile = tempFile();
  let srv = await startServer({ key: 'party', dataFile });
  const port = new URL(srv.url).port;
  const a = await open(srv.url + '/ade/#k=party');
  const b = await open(srv.url + '/ade/#k=party');
  await waitMode(a.page, 'server');
  await waitMode(b.page, 'server');

  await setNames(a.page, ['Alex', 'Ben', 'Chris', 'Dana']);
  await b.page.waitForFunction(() => ADE.state.members.p2.name === 'Ben', null, { timeout: 15000 });
  await a.page.locator('.chip', { hasText: 'Alex' }).click();
  await addExpense(a.page, { amount: '90', title: 'Pizza', payer: 'Alex' });
  await b.page.waitForFunction(() => Object.values(ADE.state.items).some(i => i.title === 'Pizza'), null, { timeout: 15000 });
  assert.deepEqual(await balances(b.page), { Alex: 6750, Ben: -2250, Chris: -2250, Dana: -2250 });

  // Ohne Code: gesperrt, mit Code: drin
  const c = await open(srv.url + '/ade/');
  await waitMode(c.page, 'locked');
  await c.page.locator('#keyDialog input').fill('party');
  await c.page.locator('#keyDialog').getByRole('button', { name: 'Weiter' }).click();
  await waitMode(c.page, 'server');
  await c.page.waitForFunction(() => Object.values(ADE.state.items).some(i => i.title === 'Pizza'));

  // Server weg → offline eintragen → Server wieder da → kommt bei allen an
  await srv.stop();
  await addExpense(a.page, { amount: '30', title: 'Späti', payer: 'Alex' });
  await waitMode(a.page, 'offline');
  srv = await startServer({ key: 'party', dataFile, port });
  await waitMode(a.page, 'server');
  await b.page.waitForFunction(() => Object.values(ADE.state.items).some(i => i.title === 'Späti'), null, { timeout: 15000 });

  assert.deepEqual([...a.errors, ...b.errors, ...c.errors], []);
  for (const x of [a, b, c]) await x.context.close();
  await srv.stop();
});

