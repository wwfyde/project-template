import { createFileRoute, redirect } from '@tanstack/react-router'

import { AuthenticatedShell } from '../app/layout/authenticated-shell'

export const Route = createFileRoute('/_authenticated')({
  beforeLoad: async ({ context, location }) => {
    const user = await context.auth.ensureSession()
    if (!user) {
      throw redirect({ to: '/login', search: { redirect: location.href }, replace: true })
    }
    return { user }
  },
  component: AuthenticatedShell,
})
