import { createFileRoute } from '@tanstack/react-router'

import { AgentPage } from '../../features/agent'

export const Route = createFileRoute('/_authenticated/agent')({
  component: AgentPage,
})
