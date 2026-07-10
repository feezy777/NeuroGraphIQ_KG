import { useState, useEffect, type ComponentType } from 'react'
import { I18nProvider } from './i18n-context'
import { WorkbenchLogProvider } from './logging/WorkbenchLogContext'
import { WorkbenchLayout } from './layout/WorkbenchLayout'
import { DashboardPage } from './pages/DashboardPage'
import { SymptomQueryPage } from './pages/SymptomQueryPage'
import { GranularityProvider } from './hooks/useGlobalGranularity'
import { ResourcesPage } from './pages/ResourcesPage'
import { FilesPage } from './pages/FilesPage'
import { ImportBatchesPage } from './pages/ImportBatchesPage'
import { ImportPipelinePage } from './pages/ImportPipelinePage'
import { DataCenterPage } from './pages/data-center/DataCenterPage'
import { LegacyDataCenterRedirect } from './pages/data-center/LegacyDataCenterRedirect'
import { LlmExtractionPage } from './pages/LlmExtractionPage'
import { RuleValidationPage } from './pages/RuleValidationPage'
import { HumanReviewPage } from './pages/HumanReviewPage'
import { PromotionsPage } from './pages/PromotionsPage'
import { SettingsPage } from './pages/SettingsPage'
import { MirrorKgPage } from './pages/MirrorKgPage'
import { BackgroundTaskCenterPage } from './pages/BackgroundTaskCenter'
import { GraphExplorerPage } from './pages/GraphExplorerPage'
import { TaskDetailModalProvider } from './components/TaskDetailModal'

const ROUTES: Record<string, ComponentType> = {
  '/': DashboardPage,
  '/resources': ResourcesPage,
  '/files': FilesPage,
  '/import-batches': ImportBatchesPage,
  '/import-pipeline': ImportPipelinePage,
  '/data-center': DataCenterPage,
  '/llm-extraction': LlmExtractionPage,
  '/mirror-kg': MirrorKgPage,
  '/task-center': BackgroundTaskCenterPage,
  '/graph-explorer': GraphExplorerPage,
  '/symptom-query': SymptomQueryPage,
  '/rule-validation': RuleValidationPage,
  '/human-review': HumanReviewPage,
  '/promotions': PromotionsPage,
  '/settings': SettingsPage,
}

/** Legacy paths redirect into Data Center tabs. */
const LEGACY_REDIRECTS: Record<string, string> = {
  '/raw-aal3': '/data-center?tab=raw&rawTab=aal3',
  '/raw-macro96': '/data-center?tab=raw&rawTab=macro96',
  '/candidates': '/data-center?tab=candidates',
  '/raw-aal3-labels': '/data-center?tab=raw&rawTab=aal3',
  '/raw-macro96-rows': '/data-center?tab=raw&rawTab=macro96',
  '/candidate-regions': '/data-center?tab=candidates',
}

function getPath(): string {
  const h = window.location.hash.slice(1)
  return h || '/'
}

export default function App() {
  const [path, setPath] = useState(getPath)

  useEffect(() => {
    const handler = () => setPath(getPath())
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
  }, [])

  const basePath = path.split('?')[0] || '/'
  const legacyTarget = LEGACY_REDIRECTS[basePath]
  const Page = legacyTarget
    ? () => <LegacyDataCenterRedirect target={legacyTarget} />
    : (ROUTES[basePath] ?? DashboardPage)

  return (
    <I18nProvider>
      <TaskDetailModalProvider>
        <WorkbenchLogProvider>
          <GranularityProvider>
            <WorkbenchLayout currentPath={path}>
              <Page />
            </WorkbenchLayout>
          </GranularityProvider>
        </WorkbenchLogProvider>
      </TaskDetailModalProvider>
    </I18nProvider>
  )
}
