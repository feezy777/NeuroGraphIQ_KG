import { createContext } from 'react'
import type { Language } from './i18n'

export interface I18nContextValue {
  language: Language
  setLanguage: (language: Language) => void
  t: (key: string, params?: Record<string, string | number>) => string
}

/** Stable context object — keep in a separate module so HMR does not recreate it. */
export const I18nContext = createContext<I18nContextValue | null>(null)
