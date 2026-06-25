import React from 'react'
import {
  LayoutDashboard,
  Database,
  FileText,
  Package,
  Layers,
  CheckCircle2,
  Eye,
  ArrowUpToLine,
  Sparkles,
  Settings,
} from 'lucide-react'
import { useI18n } from '../i18n-context'
import { useWorkbenchLog } from '../logging/useWorkbenchLog'
import { BottomLogConsole } from '../components/BottomLogConsole'

const NAV_ITEMS = [
  { path: '/', labelKey: 'nav.dashboard', icon: LayoutDashboard },
  { path: '/resources', labelKey: 'nav.resources', icon: Database },
  { path: '/files', labelKey: 'nav.files', icon: FileText },
  { path: '/import-batches', labelKey: 'nav.importBatches', icon: Package },
  { path: '/llm-extraction', labelKey: 'nav.llmExtraction', icon: Sparkles },
  { path: '/data-center', labelKey: 'nav.dataCenter', icon: Layers },
  { path: '/rule-validation', labelKey: 'nav.ruleValidation', icon: CheckCircle2 },
  { path: '/human-review', labelKey: 'nav.humanReview', icon: Eye },
  { path: '/promotions', labelKey: 'nav.promotions', icon: ArrowUpToLine },
  { path: '/settings', labelKey: 'nav.settings', icon: Settings },
]

interface WorkbenchLayoutProps {
  currentPath: string
  children: React.ReactNode
}

export function WorkbenchLayout({ currentPath, children }: WorkbenchLayoutProps) {
  const activePath = currentPath.split('?')[0] || '/'
  const { t } = useI18n()
  const { expanded } = useWorkbenchLog()

  return (
    <div className={`layout${expanded ? ' log-console-expanded' : ' log-console-collapsed'}`}>
      <header className="topbar">
        <span className="topbar-title">NeuroGraphIQ</span>
        <span className="topbar-sub">{t('layout.subtitle')}</span>
        <div className="topbar-right">
          <span className="topbar-version">v3.2.9-mvp1</span>
          <span className="topbar-dot" title={t('layout.readonlyMode')} />
        </div>
      </header>

      <nav className="sidebar">
        <div className="nav-group-label">{t('nav.group')}</div>
        {NAV_ITEMS.map(item => (
          <a
            key={item.path}
            href={`#${item.path}`}
            className={`nav-item${activePath === item.path ? ' active' : ''}`}
          >
            <item.icon size={14} />
            {t(item.labelKey)}
          </a>
        ))}
      </nav>

      <main className={`main${activePath === '/data-center' ? ' main-data-center' : ''}${activePath === '/llm-extraction' ? ' main-llm-data-first' : ''}`}>{children}</main>
      <BottomLogConsole />
    </div>
  )
}
