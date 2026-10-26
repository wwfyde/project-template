import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { copyFileSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));

function fixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'project-stop-'));
  for (const name of ['scripts', 'api', 'web', 'bin', 'other']) mkdirSync(join(directory, name));
  copyFileSync(join(root, 'justfile'), join(directory, 'justfile'));
  copyFileSync(join(root, 'scripts/stop-dev.mjs'), join(directory, 'scripts/stop-dev.mjs'));
  writeFileSync(join(directory, 'package.json'), '{"type":"module"}');
  const env = { ...process.env };
  delete env.API_PORT;
  delete env.WEB_PORT;
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return { directory, env };
}

function stop(f, args = [], env = {}) {
  return spawnSync('just', ['stop', ...args], {
    cwd: f.directory, env: { ...f.env, ...env }, encoding: 'utf8', timeout: 15000,
  });
}

async function listener(t, f, { kind = 'web', outside = false, stubborn = false, reload = false } = {}) {
  const name = kind === 'api' ? 'uvicorn' : 'vite.mjs';
  const file = join(f.directory, name);
  const worker = join(f.directory, 'worker.mjs');
  const listening = `
    import net from 'node:net';
    const server = net.createServer();
    server.on('error', error => { console.error(error.message); process.exit(1); });
    server.listen(0, '127.0.0.1', () => process.send({ port: server.address().port, pid: process.pid }));
    ${stubborn ? "process.on('SIGTERM', () => {});" : ''}
  `;
  writeFileSync(worker, listening);
  writeFileSync(file, reload ? `
    import { spawn } from 'node:child_process';
    const child = spawn(process.execPath, [${JSON.stringify(worker)}], { stdio: ['ignore', 'ignore', 'inherit', 'ipc'] });
    child.on('message', message => process.send(message));
    child.on('exit', code => process.exit(code ?? 0));
    process.on('SIGTERM', () => child.kill('SIGTERM'));
  ` : listening);
  const cwd = outside ? tmpdir() : join(f.directory, kind);
  const child = spawn(process.execPath, [file, ...(kind === 'api' ? ['api.main:app', '--reload'] : [])], {
    cwd, stdio: ['ignore', 'ignore', 'pipe', 'ipc'],
  });
  let errors = '';
  child.stderr.on('data', chunk => { errors += chunk; });
  const message = await new Promise((resolve, reject) => {
    child.once('message', resolve);
    child.once('exit', code => reject(new Error(`Listener exited ${code}: ${errors}`)));
  });
  t.after(() => {
    for (const pid of new Set([message.pid, child.pid])) {
      try { process.kill(pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
    }
  });
  return { ...message, child };
}

function listening(port) {
  const result = spawnSync('lsof', ['-nP', '-a', `-iTCP:${port}`, '-sTCP:LISTEN', '-t'], { encoding: 'utf8' });
  return Boolean(result.stdout.trim());
}

test('stop preserves default/env/dotenv/flag precedence and validates before discovery', t => {
  const f = fixture(t);
  writeFileSync(join(f.directory, 'bin/lsof'), '#!/bin/sh\nexit 1\n', { mode: 0o755 });
  f.env.PATH = `${join(f.directory, 'bin')}:${f.env.PATH}`;
  let result = stop(f);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /WEB_PORT=5173/);
  assert.match(result.stdout, /API_PORT=8000/);
  writeFileSync(join(f.directory, '.env'), 'WEB_PORT=6173\nAPI_PORT=9036\n');
  result = stop(f);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /WEB_PORT=6173/);
  assert.match(result.stdout, /API_PORT=9036/);
  result = stop(f, [], { WEB_PORT: '6174', API_PORT: '9037' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /WEB_PORT=6174/);
  result = stop(f, ['--web-port', '6175', '--api-port', '9038'], { WEB_PORT: 'bad', API_PORT: 'bad' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /API_PORT=9038/);
  for (const args of [['--web-port', 'bad'], ['--api-port', '65536'], ['--web-port', '1', '--api-port', '1']]) {
    result = stop(f, args);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /1–65535|不同端口/);
  }
});

test('stop frees Vite and reload worker ports, then succeeds when repeated', async t => {
  const f = fixture(t);
  const web = await listener(t, f);
  const api = await listener(t, f, { kind: 'api', reload: true });
  assert.notEqual(api.pid, api.child.pid);
  const exits = [once(web.child, 'exit'), once(api.child, 'exit')];
  const args = ['--web-port', String(web.port), '--api-port', String(api.port)];
  const result = stop(f, args);
  assert.equal(result.status, 0, result.stderr);
  await Promise.all(exits);
  assert.equal(listening(web.port), false);
  assert.equal(listening(api.port), false);
  assert.equal(stop(f, args).status, 0);
});

test('stop retains another project even with a matching Vite command', async t => {
  const f = fixture(t);
  const web = await listener(t, f, { outside: true });
  const api = await listener(t, f, { kind: 'api' });
  const result = stop(f, ['--web-port', String(web.port), '--api-port', String(api.port)]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /已保留/);
  assert.equal(listening(web.port), true);
  assert.equal(listening(api.port), false);
});

test('stop escalates only the captured service when SIGTERM is ignored', async t => {
  const f = fixture(t);
  const web = await listener(t, f, { stubborn: true });
  const api = await listener(t, f, { kind: 'api' });
  const exited = once(web.child, 'exit');
  const result = stop(f, ['--web-port', String(web.port), '--api-port', String(api.port)]);
  assert.equal(result.status, 0, result.stderr);
  const [, signal] = await exited;
  assert.equal(signal, 'SIGKILL');
  assert.equal(listening(web.port), false);
  await delay(10);
});
