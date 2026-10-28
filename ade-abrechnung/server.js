'use strict';
/*
 * Mini-Server für den Live-Abgleich der Abrechnung.
 * Liefert index.html aus und speichert die Einträge der Gruppe in einer JSON-Datei.
 * Keine Abhängigkeiten, Node.js ab Version 18.
 *
 *   GROUP_KEY=geheim node server.js
 *
 *   PORT        Port (Standard 8080)
 *   GROUP_KEY   Zugangscode; ohne Code kann jeder mit dem Link lesen und schreiben
 *   DATA_FILE   Speicherort der Daten (Standard ./data/ade.json)
 */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const PORT = process.env.PORT ? Number(process.env.PORT) : 8080;
const GROUP_KEY = process.env.GROUP_KEY || '';
const DATA_FILE = path.resolve(process.env.DATA_FILE || path.join(__dirname, 'data', 'ade.json'));
const INDEX_HTML = fs.readFileSync(path.join(__dirname, 'index.html'));

const COLLECTIONS = ['meta', 'members', 'items'];
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;
const MAX_BODY_BYTES = 1_000_000;
const MAX_RECORD_BYTES = 4_000;
const MAX_RECORDS = 5_000;
const CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  'font-src data:',
  "img-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join('; ');

const dict = () => Object.create(null);

// --- Speicher ---------------------------------------------------------------
function emptyDb() {
  return { rev: 0, meta: dict(), members: dict(), items: dict() };
}

function loadDb() {
  let raw;
  try {
    raw = fs.readFileSync(DATA_FILE, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') return emptyDb();
    throw err;
  }
  try {
    const parsed = JSON.parse(raw);
    const db = emptyDb();
    db.rev = Number.isSafeInteger(parsed.rev) ? parsed.rev : 0;
    for (const col of COLLECTIONS) {
      for (const rec of Object.values(parsed[col] || {})) {
        if (validRecord(rec)) db[col][rec.id] = rec;
      }
    }
    return db;
  } catch {
    // Kaputte Datei nicht überschreiben, sondern beiseitelegen.
    const backup = `${DATA_FILE}.kaputt-${Date.now()}`;
    fs.renameSync(DATA_FILE, backup);
    console.error(`Datendatei war nicht lesbar und liegt jetzt unter ${backup}. Starte mit leeren Daten.`);
    return emptyDb();
  }
}

function saveDb() {
  fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
  const tmp = `${DATA_FILE}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(db));
  fs.renameSync(tmp, DATA_FILE);
}

let db = loadDb();

// --- Zusammenführen: neuere Version gewinnt (gleiche Regel wie in index.html) -------
function isNewer(a, b) {
  if (!b) return true;
  if (a.u !== b.u) return a.u > b.u;
  return JSON.stringify(a) > JSON.stringify(b);
}

// Der Server prüft nur das Nötigste – die Apps prüfen jeden Datensatz selbst.
function validRecord(rec) {
  return !!rec && typeof rec === 'object' && !Array.isArray(rec)
    && typeof rec.id === 'string' && ID_RE.test(rec.id)
    && Number.isFinite(rec.u) && rec.u > 0
    && JSON.stringify(rec).length <= MAX_RECORD_BYTES;
}

function countRecords() {
  return COLLECTIONS.reduce((n, col) => n + Object.keys(db[col]).length, 0);
}

function applyRecords(list) {
  if (!Array.isArray(list)) throw httpError(400, 'records fehlt');
  let changed = 0;
  for (const entry of list.slice(0, MAX_RECORDS)) {
    const col = entry && entry.col;
    const rec = entry && entry.rec;
    if (!COLLECTIONS.includes(col) || !validRecord(rec)) continue;
    const current = db[col][rec.id];
    if (!current && countRecords() >= MAX_RECORDS) continue;
    if (isNewer(rec, current)) {
      db[col][rec.id] = rec;
      changed++;
    }
  }
  if (changed) {
    db.rev++;
    saveDb();
  }
  return changed;
}

// --- HTTP -----------------------------------------------------------------------
function httpError(status, message) {
  return Object.assign(new Error(message), { status });
}

function sendJson(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

function authorized(req) {
  if (!GROUP_KEY) return true;
  const given = Buffer.from(String(req.headers['x-group-key'] || ''));
  const wanted = Buffer.from(encodeURIComponent(GROUP_KEY));
  return given.length === wanted.length && crypto.timingSafeEqual(given, wanted);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(httpError(413, 'zu groß'));
        req.destroy();
      } else {
        chunks.push(chunk);
      }
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(httpError(400, 'kein gültiges JSON'));
      }
    });
    req.on('error', reject);
  });
}

const snapshot = () => ({ ade: 1, rev: db.rev, meta: db.meta, members: db.members, items: db.items });

// Die API-Pfade werden am Ende erkannt, damit die App auch unter einem Unterpfad
// wie yland.media/ade/ läuft – egal, ob der Proxy den Präfix entfernt oder nicht.
async function handle(req, res) {
  const url = new URL('http://localhost' + req.url);
  const p = url.pathname;

  if (p.endsWith('/healthz')) return sendJson(res, 200, { ok: true });

  if (p.endsWith('/api/state')) {
    if (req.method !== 'GET') return sendJson(res, 405, { error: 'Methode nicht erlaubt' });
    if (!authorized(req)) return sendJson(res, 401, { ade: 1, error: 'Zugangscode fehlt oder falsch' });
    if (url.searchParams.get('since') === String(db.rev)) return sendJson(res, 200, { ade: 1, rev: db.rev, unchanged: true });
    return sendJson(res, 200, snapshot());
  }

  if (p.endsWith('/api/push')) {
    if (req.method !== 'POST') return sendJson(res, 405, { error: 'Methode nicht erlaubt' });
    if (!authorized(req)) return sendJson(res, 401, { ade: 1, error: 'Zugangscode fehlt oder falsch' });
    const body = await readJson(req);
    applyRecords(body && body.records);
    return sendJson(res, 200, snapshot());
  }

  if (p.includes('/api/')) return sendJson(res, 404, { error: 'Nicht gefunden' });
  if (req.method !== 'GET' && req.method !== 'HEAD') return sendJson(res, 405, { error: 'Methode nicht erlaubt' });

  // „/ade“ → „/ade/“, damit relative API-Adressen im Browser stimmen
  const last = p.split('/').pop();
  if (!p.endsWith('/') && !last.includes('.')) {
    res.writeHead(301, { Location: p + '/' + url.search });
    return res.end();
  }

  res.writeHead(200, {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-cache',
    'Content-Security-Policy': CSP,
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Robots-Tag': 'noindex, nofollow',
  });
  res.end(req.method === 'HEAD' ? undefined : INDEX_HTML);
}

const server = http.createServer((req, res) => {
  handle(req, res).catch(err => {
    if (!err.status) console.error(err);
    if (!res.headersSent) sendJson(res, err.status || 500, { error: err.status ? err.message : 'Serverfehler' });
  });
});

server.listen(PORT, () => {
  console.log(`Abrechnung läuft auf Port ${server.address().port} · Daten: ${DATA_FILE}`);
  if (!GROUP_KEY) console.warn('Achtung: Kein GROUP_KEY gesetzt – jeder mit dem Link kann lesen und schreiben.');
});

// Gespeichert wird synchron, deshalb kann der Prozess sofort enden (z. B. bei docker stop).
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => process.exit(0));
