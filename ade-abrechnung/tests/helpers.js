'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const INDEX_URL = 'file://' + path.join(ROOT, 'index.html');

function tempFile(name = 'ade.json') {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ade-test-')), name);
}

// Startet server.js auf einem freien Port und wartet, bis er lauscht.
function startServer({ key = 'test-key', dataFile = tempFile(), port = 0 } = {}) {
  const child = spawn(process.execPath, [path.join(ROOT, 'server.js')], {
    env: { ...process.env, PORT: String(port), GROUP_KEY: key, DATA_FILE: dataFile },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  return new Promise((resolve, reject) => {
    const onData = chunk => {
      log += chunk;
      const m = /Port (\d+)/.exec(log);
      if (m) {
        child.stdout.off('data', onData);
        const stop = () => new Promise(done => {
          if (child.exitCode != null) return done();
          child.once('exit', () => done());
          child.kill('SIGTERM');
        });
        resolve({ url: `http://127.0.0.1:${m[1]}`, dataFile, stop, log: () => log });
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', chunk => { log += chunk; });
    child.once('exit', code => reject(new Error(`Server beendet (${code}): ${log}`)));
  });
}

function loadPlaywright() {
  try {
    return require('playwright');
  } catch {
    return null;
  }
}

module.exports = { ROOT, INDEX_URL, tempFile, startServer, loadPlaywright };
