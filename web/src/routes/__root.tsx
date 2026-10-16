import { createRootRouteWithContext } from '@tanstack/react-router'

import { RootLayout } from '../app/layout/root-layout'
import type { RouterAuth } from '../features/auth'

export const Route = createRootRouteWithContext<{ auth: RouterAuth }>()({ component: RootLayout })
