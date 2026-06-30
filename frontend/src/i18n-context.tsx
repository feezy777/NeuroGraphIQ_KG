// @refresh reset
import { useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import {
  getInitialLanguage,
  saveLanguage,
  translate,
  type Language,
} from './i18n'
import { I18nContext, type I18nContextValue } from './i18n-context-core'

export type { I18nContextValue }

function buildFallbackI18n(): I18nContextValue {
  const language = getInitialLanguage()
  return {
    language,
    setLanguage: saveLanguage,
    t: (key, params) => translate(language, key, params),
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(getInitialLanguage)

  const setLanguage = useCallback((next: Language) => {
    saveLanguage(next)
    setLanguageState(next)
  }, [])

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => translate(language, key, params),
    [language],
  )

  const value = useMemo(
    () => ({ language, setLanguage, t }),
    [language, setLanguage, t],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (ctx) {
    return ctx
  }

  if (import.meta.env.DEV) {
    console.warn(
      '[useI18n] Missing I18nProvider — using fallback translations. '
      + 'If this persists after a hard refresh, check App.tsx provider wiring.',
    )
    return buildFallbackI18n()
  }

  throw new Error('useI18n must be used within I18nProvider')
}
