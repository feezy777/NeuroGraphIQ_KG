import { useCallback, useEffect, useMemo, useState } from 'react'
import { PageHeader } from '../../components/PageHeader'
import { useI18n } from '../../i18n-context'
import { readHashQueryParams, buildHashUrl } from '../../utils/pipelineNavigation'
import { useGlobalGranularity } from '../../hooks/useGlobalGranularity'
import { DataCenterTabBar } from './DataCenterTabBar'
import { DataCenterOverview } from './DataCenterOverview'
import { RawDataPanel } from './RawDataPanel'
import { CandidateRegionsPanel } from './CandidateRegionsPanel'
import { MirrorKgPanel } from './MirrorKgPanel'
import { MacroClinicalDataPanel } from './MacroClinicalDataPanel'
import { FinalKgDataPanel } from './FinalKgDataPanel'
import { ExportPackagesPanel } from './ExportPackagesPanel'
import { useDataCenterCounts } from './useDataCenterCounts'
import {
  DATA_CENTER_TABS,
  DEFAULT_NAV,
  type DataCenterNavState,
  type DataCenterTabId,
  type RawDataSubTab,
  type MirrorKgSubTab,
  type MacroClinicalSubTab,
  type FinalKgSubTab,
} from './dataCenterTypes'

function parseNavFromUrl(): DataCenterNavState {
  const q = readHashQueryParams()
  const tab = DATA_CENTER_TABS.includes(q.tab as DataCenterTabId) ? (q.tab as DataCenterTabId) : DEFAULT_NAV.tab
  return {
    tab,
    rawTab: q.rawTab === 'macro96' ? 'macro96' : 'aal3',
    mirrorTab: (['connections', 'functions', 'circuits', 'triples', 'evidence'].includes(q.mirrorTab)
      ? q.mirrorTab : DEFAULT_NAV.mirrorTab) as MirrorKgSubTab,
    macroTab: (['circuit_steps', 'projection_functions', 'memberships', 'circuit_functions', 'cross_validation', 'dual_model'].includes(q.macroTab)
      ? q.macroTab : DEFAULT_NAV.macroTab) as MacroClinicalSubTab,
    finalTab: (['circuit', 'circuit_step', 'projection', 'projection_function', 'membership', 'region_function', 'circuit_function', 'triple', 'evidence'].includes(q.finalTab)
      ? q.finalTab : DEFAULT_NAV.finalTab) as FinalKgSubTab,
    batchId: q.batch_id ?? '',
    resourceId: q.resource_id ?? '',
    sourceAtlas: q.source_atlas ?? '',
    granularityLevel: '',  // set by Context, not hash
  }
}

function navToQuery(nav: DataCenterNavState): Record<string, string | undefined> {
  return {
    tab: nav.tab === 'overview' ? undefined : nav.tab,
    rawTab: nav.tab === 'raw' ? nav.rawTab : undefined,
    mirrorTab: nav.tab === 'mirror' ? nav.mirrorTab : undefined,
    macroTab: nav.tab === 'macro' ? nav.macroTab : undefined,
    finalTab: nav.tab === 'final' ? nav.finalTab : undefined,
    batch_id: nav.batchId || undefined,
    resource_id: nav.resourceId || undefined,
    source_atlas: nav.sourceAtlas || undefined,
    granularity_level: readHashQueryParams().granularity_level || undefined,
  }
}

export function DataCenterPage() {
  const { t } = useI18n()
  const [nav, setNav] = useState<DataCenterNavState>(() => parseNavFromUrl())
  const { granularity } = useGlobalGranularity()
  const { counts, loading, refresh } = useDataCenterCounts(granularity)

  useEffect(() => {
    const handler = () => setNav(parseNavFromUrl())
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
  }, [])

  const updateNav = useCallback((patch: Partial<DataCenterNavState>) => {
    setNav(prev => {
      const next = { ...prev, ...patch }
      window.location.hash = buildHashUrl('/data-center', navToQuery(next))
      return next
    })
  }, [])

  const setTab = useCallback((tab: DataCenterTabId) => updateNav({ tab }), [updateNav])

  const workspace = useMemo(() => {
    switch (nav.tab) {
      case 'overview':
        return <DataCenterOverview counts={counts} loading={loading} onNavigate={setTab} onRefresh={refresh} />
      case 'raw':
        return (
          <RawDataPanel
            rawTab={nav.rawTab}
            onRawTabChange={(rawTab: RawDataSubTab) => updateNav({ tab: 'raw', rawTab })}
          />
        )
      case 'candidates':
        return <CandidateRegionsPanel />
      case 'mirror':
        return (
          <MirrorKgPanel
            mirrorTab={nav.mirrorTab}
            onMirrorTabChange={(mirrorTab: MirrorKgSubTab) => updateNav({ tab: 'mirror', mirrorTab })}
            batchId={nav.batchId}
            resourceId={nav.resourceId}
            sourceAtlas={nav.sourceAtlas}
            granularityLevel={granularity}
            onFilterChange={patch => updateNav({
              batchId: patch.batchId ?? nav.batchId,
              resourceId: patch.resourceId ?? nav.resourceId,
              sourceAtlas: patch.sourceAtlas ?? nav.sourceAtlas,
            })}
          />
        )
      case 'macro':
        return (
          <MacroClinicalDataPanel
            macroTab={nav.macroTab}
            onMacroTabChange={(macroTab: MacroClinicalSubTab) => updateNav({ tab: 'macro', macroTab })}
            batchId={nav.batchId}
            resourceId={nav.resourceId}
            sourceAtlas={nav.sourceAtlas}
            granularityLevel={granularity}
            onFilterChange={patch => updateNav({
              batchId: patch.batchId ?? nav.batchId,
              resourceId: patch.resourceId ?? nav.resourceId,
              sourceAtlas: patch.sourceAtlas ?? nav.sourceAtlas,
            })}
          />
        )
      case 'final':
        return (
          <FinalKgDataPanel
            finalTab={nav.finalTab}
            onFinalTabChange={(finalTab: FinalKgSubTab) => updateNav({ tab: 'final', finalTab })}
          />
        )
      case 'exports':
        return <ExportPackagesPanel />
      default:
        return <DataCenterOverview counts={counts} loading={loading} onNavigate={setTab} onRefresh={refresh} />
    }
  }, [nav, counts, loading, refresh, setTab, updateNav, granularity])

  return (
    <div className="data-center-page">
      <div className="data-center-header-static">
        <PageHeader title={t('dataCenter.title')} description={t('dataCenter.subtitle')} readonly />
        <DataCenterTabBar activeTab={nav.tab} onTabChange={setTab} />
      </div>
      <div className="data-center-workspace">{workspace}</div>
    </div>
  )
}
