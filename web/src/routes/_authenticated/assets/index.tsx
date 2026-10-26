import { createFileRoute } from '@tanstack/react-router'

import { ImagesPage } from '../../../features/images/ui/images-page'

export const Route = createFileRoute('/_authenticated/assets/')({
  component: ImagesPage,
})
