import path from 'node:path'
import { loadEnv, type ServerOptions } from 'vite'

function readPort(env: Record<string, string>, name: string, fallback: number): number {
  const value = env[name] ?? String(fallback)
  const port = Number(value)
  if (!/^\d+$/.test(value) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535, received: ${value}`)
  }
  return port
}

export function devServerOptions(mode: string, webRoot: string): ServerOptions {
  // loadEnv gives exported shell variables priority over each directory's files.
  // The web package can override workspace defaults without exposing either to clients.
  const prefixes = ['WEB_PORT', 'API_PORT']
  const env = {
    ...loadEnv(mode, path.resolve(webRoot, '..'), prefixes),
    ...loadEnv(mode, webRoot, prefixes),
  }
  const port = readPort(env, 'WEB_PORT', 5173)
  const apiPort = readPort(env, 'API_PORT', 8000)

  return {
    port,
    strictPort: true,
    proxy: {
      '^/api(?:/|$)': {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: true,
        ws: true,
      },
    },
  }
}
