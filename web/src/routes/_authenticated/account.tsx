import { createFileRoute } from '@tanstack/react-router'

import { parseAccountSearch } from '../../features/account/model/account'
import { AccountPage } from '../../features/account/ui/account-page'

export const Route = createFileRoute('/_authenticated/account')({
  validateSearch: parseAccountSearch,
  component: AccountPage,
})
