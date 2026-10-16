import { createContext } from 'react'

import type { Auth } from './model/auth'

export const AuthContext = createContext<Auth | null>(null)
