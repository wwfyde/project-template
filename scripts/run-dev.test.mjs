import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));

function fixture(t, extraEnv = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'project-template-dev-'));
  const bin = join(directory, 'bin');
  mkdirSync(bin);
  const service = join(directory, 'service.mjs');
  writeFileSync(service, `
    import { spawn } from 'node:child_process';
    import { existsSync, writeFileSync } from 'node:fs';
    const service = process.argv[2];
    const record = { service, args: process.argv.slice(3), cwd: process.cwd(),
      webPort: process.env.WEB_PORT, apiPort: process.env.API_PORT, pid: process.pid };
    if (process.env.HOLD_SERVICE) {
      record.childPid = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' }).pid;
      setInterval(() => {
        if (process.env.FAIL_SERVICE === service &&
          ['api', 'web'].every(name => existsSync(process.env.RECORD_DIR + '/' + name + '.json'))) process.exit(42);
      }, 20);
    }
    writeFileSync(process.env.RECORD_DIR + '/' + service + '.json', JSON.stringify(record));
  `);
  for (const [command, name] of [['pnpm', 'web'], ['uv', 'api']]) {
    writeFileSync(join(bin, command), `#!/bin/sh\nif [ "$1" = exec ]; then shift; exec "$@"; fi\nexec '${process.execPath}' '${service}' '${name}' "$@"\n`, { mode: 0o755 });
  }
  const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, RECORD_DIR: directory };
  delete env.WEB_PORT;
  delete env.API_PORT;
  Object.assign(env, extraEnv);
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return {
    env,
    read: (name) => JSON.parse(readFileSync(join(directory, `${name}.json`), 'utf8')),
  };
}

function run(args, env) {
  return spawnSync('just', ['--no-dotenv', ...args], { cwd: root, env, encoding: 'utf8', timeout: 5000 });
}

async function until(check, timeout = 6000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      if (check()) return;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    await delay(30);
  }
  assert.fail('Timed out waiting for development processes');
}

function isRunning(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
    return false;
  }
}

function launch(t, env) {
  const process = spawn('just', ['--no-dotenv', 'run', '--web-port', '5211', '--api-port', '8011'], {
    cwd: root, env, detached: true, stdio: 'ignore',
  });
  t.after(() => {
    try { globalThis.process.kill(-process.pid, 'SIGTERM'); } catch (error) {
      if (error.code !== 'ESRCH') throw error;
    }
  });
  return process;
}

test('web supports default, environment, --port and -p with flags taking precedence', (t) => {
  const f = fixture(t);
  for (const [args, env, expected] of [
    [[], {}, '5173'],
    [[], { WEB_PORT: '5210' }, '5210'],
    [['--port', '5211'], { WEB_PORT: 'invalid' }, '5211'],
    [['-p', '5212'], { WEB_PORT: '5210' }, '5212'],
  ]) {
    const result = run(['web', ...args], { ...f.env, ...env });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(f.read('web').args, ['--filter', 'web', 'run', 'dev', '--port', expected, '--strictPort']);
    assert.equal(f.read('web').webPort, expected);
  }
});

test('api and web reject invalid ports before starting a service', (t) => {
  const f = fixture(t);
  for (const recipe of ['api', 'web']) {
    for (const port of ['', '0', '65536', 'abc', '8000; exit 0']) {
      const result = run([recipe, '--port', port], f.env);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /1–65535/);
    }
  }
});

test('run rejects invalid or conflicting ports before starting either service', (t) => {
  const f = fixture(t);
  for (const args of [
    ['--web-port', 'bad'], ['--api-port', '65536'], ['--web-port', '8000', '--api-port', '8000'],
  ]) {
    const result = run(['run', ...args], f.env);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /1–65535|不同端口/);
  }
});

test('run propagates selected ports and stops both process trees on Ctrl+C', async (t) => {
  const f = fixture(t, { HOLD_SERVICE: '1', WEB_PORT: '9991', API_PORT: '9992' });
  const child = launch(t, f.env);
  const exited = once(child, 'exit');
  await until(() => f.read('api').childPid && f.read('web').childPid);
  const records = [f.read('api'), f.read('web')];
  for (const record of records) {
    assert.equal(record.webPort, '5211');
    assert.equal(record.apiPort, '8011');
  }
  assert.deepEqual(records[0].args, ['run', 'uvicorn', 'api.main:app', '--reload', '--port', '8011']);
  assert.equal(records[0].cwd, `${root}api`);
  process.kill(-child.pid, 'SIGINT');
  await exited;
  await until(() => records.every((record) => !isRunning(record.pid) && !isRunning(record.childPid)));
});

test('a service failure stops its sibling and descendants without stopping unrelated processes', async (t) => {
  const f = fixture(t, { HOLD_SERVICE: '1', FAIL_SERVICE: 'web' });
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
  t.after(() => unrelated.kill());
  const child = launch(t, f.env);
  const exited = once(child, 'exit');
  await until(() => f.read('api').childPid && f.read('web').childPid);
  const records = [f.read('api'), f.read('web')];
  const [code] = await exited;
  assert.equal(code, 42);
  await until(() => records.every((record) => !isRunning(record.pid) && !isRunning(record.childPid)));
  assert.equal(isRunning(unrelated.pid), true);
});
