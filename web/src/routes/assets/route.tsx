import { createFileRoute, Outlet } from '@tanstack/react-router'

export const Route = createFileRoute('/assets')({
  component: RouteComponent,
})

function RouteComponent() {
  return <Outlet />
}
