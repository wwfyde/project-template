import { createFileRoute } from '@tanstack/react-router'

import { UserMessageNavigationRailDemoPage } from '../../../features/user-message-navigation-rail-demo'

export const Route = createFileRoute('/_authenticated/examples/user-message-navigation-rail')({
  component: UserMessageNavigationRailDemoPage,
})
