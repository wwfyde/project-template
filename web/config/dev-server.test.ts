import fs from 'node:fs/promises'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { createServer as createViteServer } from 'vite'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { devServerOptions } from './dev-server.ts'

describe('development server environment', () => {
  let workspace: string
  let webRoot: string

  beforeEach(async () => {
    vi.stubEnv('WEB_PORT', undefined)
    vi.stubEnv('API_PORT', undefined)
    workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'web-dev-env-'))
    webRoot = path.join(workspace, 'web')
    await fs.mkdir(webRoot)
  })

  afterEach(async () => {
    vi.unstubAllEnvs()
    await fs.rm(workspace, { recursive: true, force: true })
  })

  it('uses defaults when neither workspace nor package configures ports', () => {
    const server = devServerOptions('development', webRoot)
    expect(server.port).toBe(5173)
    expect(server.strictPort).toBe(true)
    expect(server.proxy?.['^/api(?:/|$)']).toMatchObject({ target: 'http://127.0.0.1:8000' })
  })

  it('uses workspace dotenv values when launched directly from the web package', async () => {
    await fs.writeFile(path.join(workspace, '.env'), 'WEB_PORT=6173\nAPI_PORT=9036\n')
    const server = devServerOptions('development', webRoot)
    expect(server.port).toBe(6173)
    expect(server.proxy?.['^/api(?:/|$)']).toMatchObject({ target: 'http://127.0.0.1:9036' })
  })

  it('prefers package overrides, then exported recipe or shell variables', async () => {
    await fs.writeFile(path.join(workspace, '.env'), 'WEB_PORT=6173\nAPI_PORT=9036\n')
    await fs.writeFile(path.join(webRoot, '.env.development.local'), 'WEB_PORT=6273\nAPI_PORT=9136\n')
    expect(devServerOptions('development', webRoot).port).toBe(6273)

    vi.stubEnv('WEB_PORT', '6373')
    vi.stubEnv('API_PORT', '9236')
    const server = devServerOptions('development', webRoot)
    expect(server.port).toBe(6373)
    expect(server.proxy?.['^/api(?:/|$)']).toMatchObject({ target: 'http://127.0.0.1:9236' })
  })

  it.each(['0', '-1', '65536', 'abc', '5173.5', '5e3', ''])('rejects invalid ports: %j', (value) => {
    vi.stubEnv('WEB_PORT', value)
    expect(() => devServerOptions('development', webRoot)).toThrow('WEB_PORT must be an integer')
    vi.stubEnv('WEB_PORT', '5173')
    vi.stubEnv('API_PORT', value)
    expect(() => devServerOptions('development', webRoot)).toThrow('API_PORT must be an integer')
  })

  it('proxies API requests with their prefix, query and body intact', async () => {
    let requests = 0
    const backend = createServer(async (request, response) => {
      requests += 1
      const chunks: Buffer[] = []
      for await (const chunk of request) chunks.push(Buffer.from(chunk))
      response.setHeader('Content-Type', 'application/json')
      response.end(JSON.stringify({
        method: request.method,
        path: request.url,
        body: Buffer.concat(chunks).toString(),
      }))
    })
    await new Promise<void>((resolve) => backend.listen(0, '127.0.0.1', resolve))
    const backendPort = (backend.address() as AddressInfo).port
    vi.stubEnv('API_PORT', String(backendPort))
    let vite: Awaited<ReturnType<typeof createViteServer>> | undefined
    try {
      vite = await createViteServer({
        configFile: false,
        envFile: false,
        root: webRoot,
        appType: 'custom',
        logLevel: 'silent',
        optimizeDeps: { noDiscovery: true },
        server: { ...devServerOptions('development', webRoot), host: '127.0.0.1', port: 0 },
      })
      await vite.listen()
      const port = (vite.httpServer!.address() as AddressInfo).port
      const origin = `http://127.0.0.1:${port}`
      const response = await fetch(`${origin}/api/echo?query=hello`, {
        method: 'POST',
        body: 'payload',
      })
      expect(response.status).toBe(200)
      expect(await response.json()).toEqual({
        method: 'POST',
        path: '/api/echo?query=hello',
        body: 'payload',
      })
      expect((await fetch(`${origin}/apiary`)).status).toBe(404)
      expect(requests).toBe(1)
    } finally {
      await vite?.close()
      await new Promise<void>((resolve, reject) => backend.close((error) => error ? reject(error) : resolve()))
    }
  })
})
