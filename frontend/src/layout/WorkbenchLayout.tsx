import React, { useState, useCallback, memo } from 'react'
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
  MonitorPlay,
  Share2,
  Search,
  Brain,
} from 'lucide-react'
import { useI18n } from '../i18n-context'
import { useWorkbenchLog } from '../logging/useWorkbenchLog'
import { GranularitySwitcher } from '../components/GranularitySwitcher'
import { BottomLogConsole } from '../components/BottomLogConsole'
import { TaskCenterDropdown } from '../components/TaskCenterDropdown'
import type { BgTask } from '../hooks/useBackgroundTasks'
import { listFieldCompletionRuns, listCompositeWorkflowRuns } from '../api/endpoints'
import { useTaskDetailModal } from '../components/TaskDetailModal'

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
  { path: '/task-center', labelKey: 'nav.taskCenter', icon: MonitorPlay },
  { path: '/graph-explorer', labelKey: 'nav.graphExplorer', icon: Share2 },
  { path: '/brain-3d', labelKey: 'nav.brain3D', icon: Brain },
  { path: '/symptom-query', labelKey: 'nav.symptomQuery', icon: Search },
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
  const navigate = (path: string) => { window.location.hash = `#${path}` }
  const { openTask } = useTaskDetailModal()

  // Dropdown: fetch-on-open only, no polling
  const [ddTasks, setDdTasks] = useState<BgTask[]>([])
  const [ddLoading, setDdLoading] = useState(false)

  const fetchDropdownTasks = useCallback(async () => {
    setDdLoading(true)
    try {
      const [fcRes, cwRes] = await Promise.allSettled([
        listFieldCompletionRuns({ limit: 50 }),
        listCompositeWorkflowRuns({ limit: 50 }),
      ])
      const merged: BgTask[] = []
      if (fcRes.status === 'fulfilled') {
        for (const r of fcRes.value.items) {
          merged.push({ id: r.id, type: 'field_completion', status: r.status, targetType: r.target_type, targetCount: r.target_count, label: `字段补全 · ${r.target_type}`, provider: r.provider ?? undefined, modelName: r.model_name ?? undefined, createdAt: r.created_at, startedAt: r.started_at, completedAt: r.completed_at })
        }
      }
      if (cwRes.status === 'fulfilled') {
        for (const r of cwRes.value.items) {
          merged.push({ id: r.id, type: 'composite_workflow', status: r.status, targetType: r.workflow_type ?? undefined, targetCount: r.candidate_count, label: `LLM 提取 · ${r.workflow_type}`, provider: r.provider ?? undefined, modelName: r.model_name ?? undefined, createdAt: r.created_at ?? '', startedAt: r.started_at ?? null, completedAt: r.completed_at ?? null })
        }
      }
      merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
      setDdTasks(merged)
    } catch { /* ignore */ }
    setDdLoading(false)
  }, [])

  return (
    <div className={`layout${expanded ? ' log-console-expanded' : ' log-console-collapsed'}`}>
      <header className="topbar">
        <span className="topbar-title">NeuroGraphIQ</span>
        <span className="topbar-sub">{t('layout.subtitle')}</span>
        <div className="topbar-right">
          <TaskCenterDropdown
            tasks={ddTasks}
            loading={ddLoading}
            onViewAll={() => navigate('/task-center')}
            onViewTask={openTask}
            onOpen={fetchDropdownTasks}
          />
          <GranularitySwitcher />
          <span className="topbar-version">v3.2.9-mvp1</span>
          <span className="topbar-dot" title={t('layout.readonlyMode')} />
        </div>
      </header>

      <Sidebar activePath={activePath} t={t} />

      <MainContent activePath={activePath}>{children}</MainContent>
      <BottomLogConsole />
    </div>
  )
}

// Memoized to prevent child re-renders when Layout state changes
const Sidebar = memo(function Sidebar({ activePath, t }: { activePath: string; t: (k: string) => string }) {
  return (
    <nav className="sidebar">
      <div className="nav-group-label">{t('nav.group')}</div>
      {NAV_ITEMS.map(item => (
        <a key={item.path} href={`#${item.path}`} className={`nav-item${activePath === item.path ? ' active' : ''}`}>
          <item.icon size={14} />
          {t(item.labelKey)}
        </a>
      ))}
    </nav>
  )
})

const MainContent = memo(function MainContent({ activePath, children }: { activePath: string; children: React.ReactNode }) {
  return (
    <main className={`main${activePath === '/data-center' ? ' main-data-center' : ''}${activePath === '/llm-extraction' ? ' main-llm-data-first' : ''}${activePath === '/brain-3d' ? ' main-brain-3d' : ''}`}>
      {children}
    </main>
  )
})
