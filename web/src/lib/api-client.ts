export class ApiRequestError extends Error {
  readonly status: number
  readonly requestId: string
  readonly code?: string

  constructor(message: string, status: number, requestId: string, code?: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.requestId = requestId
    this.code = code
  }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  if (!/^\/api(?:\/|$)/.test(path) || /[\\\p{Cc}]/u.test(path)) {
    throw new Error('API requests must use a local /api path')
  }

  const headers = new Headers(init?.headers)
  const requestId = crypto.randomUUID()
  headers.set('Accept', 'application/json')
  headers.set('Request-ID', requestId)
  if (typeof init?.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  // Identity is resolved by the server session; tracing instrumentation can
  // supply its own traceparent without this helper inventing a trace.
  const response = await fetch(path, { ...init, credentials: 'include', headers })
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : null
    const structured = detail && typeof detail === 'object' ? detail : null
    const message =
      typeof detail === 'string'
        ? detail
        : structured && 'message' in structured && typeof structured.message === 'string'
          ? structured.message
          : `Request failed (${response.status})`
    const code = structured && 'code' in structured && typeof structured.code === 'string' ? structured.code : undefined
    throw new ApiRequestError(message, response.status, response.headers.get('Request-ID') ?? requestId, code)
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}
