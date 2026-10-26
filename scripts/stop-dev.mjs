import { spawnSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { relative, sep } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const root = realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const ports = { WEB_PORT: process.env.WEB_PORT, API_PORT: process.env.API_PORT };

function command(program, args, allowEmpty = false) {
  const result = spawnSync(program, args, { encoding: 'utf8', timeout: 5000, env: { ...process.env, LC_ALL: 'C' } });
  if (result.error) throw new Error(`无法执行 ${program}，请确认已安装且具有权限：${result.error.message}`);
  if (result.status === 0) return result.stdout;
  if (allowEmpty && result.status === 1 && !result.stdout && !result.stderr) return '';
  throw new Error(`${program} 检查失败，未停止无法确认归属的进程`);
}

function listeners(port) {
  return command('lsof', ['-nP', '-a', `-iTCP:${port}`, '-sTCP:LISTEN', '-Fp'], true)
    .split('\n').filter((line) => /^p\d+$/.test(line)).map((line) => Number(line.slice(1)));
}

function processInfo(pid) {
  const output = command('ps', ['-ww', '-p', String(pid), '-o', 'ppid=', '-o', 'lstart=', '-o', 'command='], true).trim();
  if (!output) return null;
  const match = output.match(/^(\d+)\s+(\S+\s+\S+\s+\d+\s+\d+:\d+:\d+\s+\d+)\s+(.+)$/);
  if (!match) throw new Error(`无法识别 PID ${pid}，未发送停止信号`);
  return { pid, parent: Number(match[1]), started: match[2], args: match[3] };
}

function belongsToProject(pid) {
  const output = command('lsof', ['-a', '-p', String(pid), '-d', 'cwd', '-Fn'], true);
  const path = output.split('\n').find((line) => line.startsWith('n'))?.slice(1);
  if (!path) return false;
  try {
    const location = relative(root, realpathSync(path));
    return location === '' || (!location.startsWith(`..${sep}`) && location !== '..' && !location.startsWith(sep));
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

function serviceRoot(pid, kind) {
  const seen = new Set();
  while (pid > 1 && pid !== process.pid && !seen.has(pid) && seen.size < 32) {
    seen.add(pid);
    const info = processInfo(pid);
    if (!info) return null;
    const matches = kind === 'API_PORT'
      ? /(?:^|[\s/])uvicorn(?:\s|$)/.test(info.args) && /(?:^|\s)api\.main:app(?:\s|$)/.test(info.args)
      : /(?:^|[\s/])vite(?:\.[cm]?js)?(?:\s|$)/.test(info.args);
    if (matches && belongsToProject(pid)) return info;
    pid = info.parent;
  }
  return null;
}

function descendants(roots) {
  const rows = command('ps', ['-axo', 'pid=', '-o', 'ppid=']).trim().split('\n')
    .map((line) => line.trim().split(/\s+/).map(Number));
  // Keep the identities verified during discovery; never adopt a reused root PID.
  const captured = new Map(roots.filter(stillMatches).map((item) => [item.pid, item]));
  let changed = true;
  while (changed) {
    changed = false;
    for (const [pid, parent] of rows) {
      if (captured.has(parent) && !captured.has(pid) && stillMatches(captured.get(parent))) {
        const info = processInfo(pid);
        if (!info || info.parent !== parent) continue;
        captured.set(pid, info);
        changed = true;
      }
    }
  }
  return [...captured.values()];
}

function stillMatches(item) {
  const current = processInfo(item.pid);
  return current?.started === item.started && current?.args === item.args;
}

function signal(item, value) {
  // Never signal a process group: standalone recipes may share the caller's group.
  if (!stillMatches(item)) return;
  try {
    process.kill(item.pid, value);
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
  }
}

async function stop() {
  for (const [name, value] of Object.entries(ports)) {
    if (!/^\d+$/.test(value ?? '') || Number(value) < 1 || Number(value) > 65535) {
      throw new Error(`${name} 必须是 1–65535 的整数`);
    }
  }
  if (Number(ports.WEB_PORT) === Number(ports.API_PORT)) throw new Error('WEB_PORT 和 API_PORT 必须使用不同端口');

  const roots = new Map();
  for (const [kind, port] of Object.entries(ports)) {
    for (const pid of listeners(port)) {
      const target = serviceRoot(pid, kind);
      if (!target) {
        console.error(`${kind}=${port} 的 PID ${pid} 无法确认为本项目服务，已保留`);
        process.exitCode = 1;
      } else {
        roots.set(target.pid, target);
      }
    }
  }

  if (roots.size) {
    const captured = descendants([...roots.values()]);
    for (const target of roots.values()) {
      console.log(`正在停止本项目服务 PID ${target.pid}`);
      signal(target, 'SIGTERM');
    }
    const deadline = Date.now() + 3000;
    while (Date.now() < deadline && captured.some(stillMatches)) await delay(100);
    for (const target of captured) signal(target, 'SIGKILL');
    // Allow the kernel and reload parent to release inherited listening sockets.
    for (let attempt = 0; attempt < 20; attempt++) {
      if (Object.values(ports).every((port) => listeners(port).length === 0)) break;
      await delay(100);
    }
  }
  for (const [kind, port] of Object.entries(ports)) {
    if (listeners(port).length) {
      console.error(`${kind}=${port} 仍被占用`);
      process.exitCode = 1;
    } else {
      console.log(`${kind}=${port} 已停止或未运行`);
    }
  }
}

stop().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
