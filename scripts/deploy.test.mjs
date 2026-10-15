import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync,
  readlinkSync, rmSync, symlinkSync, writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const apiImage = `ghcr.io/example/api@sha256:${'a'.repeat(64)}`;
const webImage = `ghcr.io/example/web@sha256:${'b'.repeat(64)}`;
const composeVariables = [
  'API_IMAGE', 'WEB_IMAGE', 'COMPOSE_PROJECT_NAME', 'APP_ENV', 'HTTP_BIND',
  'HTTP_PORT', 'POSTGRES_USER', 'POSTGRES_DB', 'POSTGRES_PASSWORD', 'REDIS_PASSWORD',
];

function fixture(t, extraEnv = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'project-template-deploy-'));
  const bin = join(directory, 'bin');
  const deployment = join(directory, 'site');
  const log = join(directory, 'commands.jsonl');
  mkdirSync(bin);
  mkdirSync(join(deployment, 'releases', 'previous'), { recursive: true });
  symlinkSync('releases/previous', join(deployment, 'current'));
  writeFileSync(join(deployment, '.env'), [
    'COMPOSE_PROJECT_NAME=project-template-test', 'APP_ENV=prod',
    'HTTP_BIND=127.0.0.1', 'HTTP_PORT=18080', 'POSTGRES_USER=app',
    'POSTGRES_DB=app', 'POSTGRES_PASSWORD=test-postgres', 'REDIS_PASSWORD=test-redis', '',
  ].join('\n'));

  const stub = join(directory, 'command.mjs');
  writeFileSync(stub, `
    import { spawnSync } from 'node:child_process';
    import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
    import { join } from 'node:path';
    const [command, ...args] = process.argv.slice(2);
    const inherited = Object.fromEntries(${JSON.stringify(composeVariables)}
      .filter(name => process.env[name] !== undefined).map(name => [name, process.env[name]]));
    appendFileSync(process.env.COMMAND_LOG, JSON.stringify({ command, args, inherited }) + '\\n');
    if (command === 'ssh') {
      const remote = args.at(-1);
      if (process.env.FAIL_APPLY_SSH && remote.startsWith('bash ')) process.exit(43);
      const child = spawnSync('bash', ['-c', remote], { env: process.env, stdio: 'inherit' });
      process.exit(child.status ?? 1);
    }
    if (command === 'flock') process.exit(process.env.FAIL_LOCK ? 44 : 0);
    if (command === 'curl') {
      if (args.at(-1).endsWith('/api/health')) process.stdout.write('{"status":"ok"}');
      process.exit(0);
    }
    if (command === 'mv') {
      // The server uses GNU mv -Tf; provide equivalent symlink replacement on macOS.
      renameSync(args.at(-2), args.at(-1));
      process.exit(0);
    }
    if (args[0] === '--config') {
      const config = args[1];
      mkdirSync(config, { recursive: true });
      writeFileSync(join(config, 'config.json'), readFileSync(0, 'utf8'));
      process.exit(process.env.FAIL_LOGIN ? 41 : 0);
    }
    const options = args.slice(1);
    while (['--env-file', '-f'].includes(options[0])) options.splice(0, 2);
    const action = options[0];
    if (action === 'run' && process.env.FAIL_MIGRATION) process.exit(42);
    if (action === 'up' && options.at(-1) === 'api' && process.env.FAIL_API) process.exit(45);
    if (action === 'port') process.stdout.write('127.0.0.1:18080\\n');
  `);
  for (const command of ['ssh', 'docker', 'flock', 'curl', 'mv']) {
    writeFileSync(join(bin, command),
      `#!/bin/sh\nexec '${process.execPath}' '${stub}' '${command}' "$@"\n`, { mode: 0o755 });
  }
  const env = { ...process.env };
  for (const name of [...composeVariables, 'DEPLOY_SSH_CONFIG', 'GHCR_TOKEN', 'GHCR_USER']) delete env[name];
  Object.assign(env, {
    PATH: `${bin}:${process.env.PATH}`, COMMAND_LOG: log, DEPLOY_PATH: deployment,
    DEPLOY_SSH_TARGET: 'test', API_IMAGE: apiImage, WEB_IMAGE: webImage,
  }, extraEnv);
  t.after(() => rmSync(directory, { recursive: true, force: true }));

  return {
    env, deployment,
    release: (id) => join(deployment, 'releases', id),
    current: () => readlinkSync(join(deployment, 'current')),
    records: () => existsSync(log)
      ? readFileSync(log, 'utf8').trim().split('\n').map(line => JSON.parse(line)) : [],
    prepare(id) {
      const release = join(deployment, 'releases', id);
      mkdirSync(join(release, '.docker'), { recursive: true });
      writeFileSync(join(release, '.docker', 'config.json'), 'test-registry-token');
      writeFileSync(join(release, 'images.env'), `API_IMAGE=${apiImage}\nWEB_IMAGE=${webImage}\n`);
      copyFileSync(join(root, 'docker-compose.yaml'), join(release, 'docker-compose.yaml'));
    },
    run(script, args) {
      return spawnSync('bash', [join(root, script), ...args], {
        cwd: root, env, encoding: 'utf8', timeout: 15000,
      });
    },
  };
}

function composeCommands(f) {
  return f.records().filter(record => record.command === 'docker' && record.args[0] === 'compose');
}

test('deploy accepts IPv4 and IPv6 bind overrides and publishes each successful release', (t) => {
  const f = fixture(t);
  for (const [index, bind] of ['127.0.0.1', '0.0.0.0', '::1', '[::1]'].entries()) {
    const id = `bind-${index}`;
    f.env.HTTP_BIND = bind;
    f.env.HTTP_PORT = '18081';
    const result = f.run('scripts/deploy.sh', ['test', id]);
    assert.equal(result.status, 0, result.stderr);
    assert.ok(readFileSync(join(f.release(id), 'images.env'), 'utf8').includes(`HTTP_BIND=${bind}\n`));
    assert.equal(f.current(), `releases/${id}`);
  }
  assert.ok(f.records().some(record => record.command === 'ssh' && record.args.includes('test')));
});

for (const [failure, status] of [['FAIL_LOGIN', 41], ['FAIL_APPLY_SSH', 43]]) {
  test(`deploy cleans registry credentials when ${failure} occurs`, (t) => {
    const f = fixture(t, { [failure]: '1', GHCR_TOKEN: 'test-token', GHCR_USER: 'test-user' });
    const result = f.run('scripts/deploy.sh', ['test', 'failed']);
    assert.equal(result.status, status, result.stderr);
    assert.equal(existsSync(join(f.release('failed'), '.docker')), false);
    assert.equal(f.current(), 'releases/previous');
  });
}

test('apply removes shell overrides before invoking Compose with saved configuration and release', (t) => {
  const f = fixture(t, Object.fromEntries(composeVariables.map(name => [name, 'stale-host-value'])));
  f.prepare('saved-env');
  const result = f.run('deploy/apply.sh', [f.deployment, 'saved-env']);
  assert.equal(result.status, 0, result.stderr);
  for (const record of composeCommands(f)) {
    assert.deepEqual(record.inherited, {});
    assert.deepEqual(record.args.slice(0, 5), [
      'compose', '--env-file', join(f.deployment, '.env'),
      '--env-file', join(f.release('saved-env'), 'images.env'),
    ]);
  }
  assert.equal(f.current(), 'releases/saved-env');
  assert.equal(existsSync(join(f.release('saved-env'), '.docker')), false);
});

test('migration failure keeps the previous release and never starts application services', (t) => {
  const f = fixture(t, { FAIL_MIGRATION: '1' });
  f.prepare('migration-failed');
  const result = f.run('deploy/apply.sh', [f.deployment, 'migration-failed']);
  assert.equal(result.status, 42, result.stderr);
  const commands = composeCommands(f);
  assert.equal(commands.filter(record => record.args.includes('run')).length, 1);
  assert.equal(commands.some(record => record.args.includes('up') && ['api', 'web'].includes(record.args.at(-1))), false);
  assert.equal(f.current(), 'releases/previous');
  assert.equal(existsSync(join(f.release('migration-failed'), '.docker')), false);
});

for (const [failure, status] of [['FAIL_LOCK', 44], ['FAIL_API', 45]]) {
  test(`apply cleans credentials and preserves current when ${failure} occurs`, (t) => {
    const f = fixture(t, { [failure]: '1' });
    f.prepare('apply-failed');
    const result = f.run('deploy/apply.sh', [f.deployment, 'apply-failed']);
    assert.equal(result.status, status, result.stderr);
    assert.equal(f.current(), 'releases/previous');
    assert.equal(existsSync(join(f.release('apply-failed'), '.docker')), false);
  });
}
