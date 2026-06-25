import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles.css'
import App from './App'
import { I18nProvider } from './i18n-context'
import { WorkbenchLogProvider } from './logging/WorkbenchLogContext'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <I18nProvider>
      <WorkbenchLogProvider>
        <App />
      </WorkbenchLogProvider>
    </I18nProvider>
  </React.StrictMode>,
)
