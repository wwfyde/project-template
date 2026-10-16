import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'

import { AppProviders } from './app/app-providers'
import { AppRouter } from './app/app-router'
import { initializeI18n } from './i18n'
import { initializeTheme } from './theme'

import './index.css'

async function bootstrap() {
  initializeTheme()
  await initializeI18n()

  const rootElement = document.getElementById('root')!
  if (!rootElement.innerHTML) {
    const root = ReactDOM.createRoot(rootElement)
    root.render(
      <StrictMode>
        <AppProviders>
          <AppRouter />
        </AppProviders>
      </StrictMode>,
    )
  }
}

void bootstrap()
