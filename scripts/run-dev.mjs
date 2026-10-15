import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const ports = { WEB_PORT: process.env.WEB_PORT, API_PORT: process.env.API_PORT };

for (const [name, value] of Object.entries(ports)) {
  if (!/^\d+$/.test(value ?? '') || Number(value) < 1 || Number(value) > 65535) {
    console.error(`${name} 必须是 1–65535 的整数`);
    process.exit(1);
  }
}

if (Number(ports.WEB_PORT) === Number(ports.API_PORT)) {
  console.error('WEB_PORT 和 API_PORT 必须使用不同端口');
  process.exit(1);
}

const children = [];
let stopping = false;

// Each recipe and its descendants have their own process group. Never kill by port/name.
function signalGroup(child, signal) {
  if (!child.pid) return;
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
  }
}

function groupIsRunning(child) {
  if (!child.pid) return false;
  try {
    process.kill(-child.pid, 0);
    return true;
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
    return false;
  }
}

function stop(exitCode) {
  if (stopping) return;
  stopping = true;
  for (const child of children) signalGroup(child, 'SIGTERM');

  // Give Vite/Uvicorn time to stop; terminate any remaining descendants after 3 seconds.
  const deadline = setTimeout(() => {
    for (const child of children) signalGroup(child, 'SIGKILL');
    process.exit(exitCode);
  }, 3000);
  const poll = setInterval(() => {
    if (children.every((child) => !groupIsRunning(child))) {
      clearTimeout(deadline);
      clearInterval(poll);
      process.exit(exitCode);
    }
  }, 50);
}

process.on('SIGINT', () => stop(130));
process.on('SIGTERM', () => stop(143));

for (const [recipe, port] of [['api', ports.API_PORT], ['web', ports.WEB_PORT]]) {
  const child = spawn('just', ['--justfile', `${root}justfile`, recipe, '--port', port], {
    cwd: root,
    env: { ...process.env, ...ports },
    stdio: 'inherit',
    detached: true,
  });
  children.push(child);
  child.on('error', (error) => {
    console.error(`无法启动 ${recipe}: ${error.message}`);
    stop(1);
  });
  child.on('exit', (code, signal) => {
    if (!stopping) {
      console.error(`${recipe} 已退出（${signal ?? code}），正在停止前后端`);
      stop(code ?? 1);
    }
  });
}
