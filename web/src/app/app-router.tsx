import { RouterProvider } from '@tanstack/react-router'
import { useMemo } from 'react'

import { useAuth } from '../features/auth'
import { router } from './router'

export function AppRouter() {
  const auth = useAuth()
  const context = useMemo(() => ({ auth }), [auth])

  return <RouterProvider router={router} context={context} />
}
