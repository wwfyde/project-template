import { createFileRoute } from '@tanstack/react-router'

import { normalizeReturnTo } from '../features/auth'
import { LoginPage } from '../features/auth/ui/login-page'

type LoginSearch = { redirect: string; error?: string }

export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    redirect: normalizeReturnTo(typeof search.redirect === 'string' ? search.redirect : undefined),
    error: typeof search.error === 'string' ? search.error : undefined,
  }),
  component: LoginPage,
})
