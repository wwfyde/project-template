import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/_authenticated/examples/conversation-navigator')({
  beforeLoad: () => {
    throw redirect({ to: '/examples/user-message-navigation-rail', replace: true })
  },
})
