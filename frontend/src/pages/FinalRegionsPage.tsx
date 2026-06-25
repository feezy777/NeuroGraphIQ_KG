import { useState, useMemo } from 'react'
import { ChevronLeft } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { KeyValuePanel } from '../components/KeyValuePanel'
import { LoadingState, ErrorState, EmptyState } from '../components/States'
import { useData } from '../hooks/useData'
import {
  fetchFinalRegions,
  fetchFinalRegionProvenance,
  type FinalBrainRegion,
  type FinalRegionProvenance,
} from '../api/endpoints'
import { useI18n } from '../i18n-context'

const LATERALITIES = ['left', 'right', 'bilateral', 'midline', 'unknown']
const GRANULARITY_LEVELS = ['macro', 'meso', 'micro', 'molecular', 'term']

function FinalRegionDetail({ region, onBack }: { region: FinalBrainRegion; onBack: () => void }) {
  const { t } = useI18n()
  const { data: prov, loading, error } = useData<FinalRegionProvenance>(
    () => fetchFinalRegionProvenance(region.id),
    [region.id],
  )

  return (
    <div>
      <button className="detail-back" onClick={onBack}>
        <ChevronLeft size={14} /> {t('finalRegions.backToList')}
      </button>
      <PageHeader title={region.raw_name} description={t('finalRegions.detailDesc')} />

      <div className="card">
        <div className="card-title">{t('finalRegions.basicInfo')}</div>
        <KeyValuePanel
          entries={[
            { label: t('common.id'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.id}</code> },
            { label: t('finalRegions.rawName'), value: region.raw_name },
            { label: t('finalRegions.stdName'), value: region.std_name },
            { label: t('common.enName'), value: region.en_name },
            { label: t('common.cnName'), value: region.cn_name },
            { label: t('common.laterality'), value: <StatusBadge status={region.laterality} /> },
            { label: t('finalRegions.baseRegion'), value: region.region_base_name },
            { label: t('finalRegions.atlas'), value: region.source_atlas },
            { label: t('common.version'), value: region.source_version },
            { label: t('finalRegions.labelValue'), value: region.label_value },
            { label: t('finalRegions.sourceLabelId'), value: region.source_label_id },
            { label: t('finalRegions.granularityLevel'), value: region.granularity_level },
            { label: t('finalRegions.granularityFamily'), value: region.granularity_family },
            { label: t('common.status'), value: <StatusBadge status={region.status} /> },
            { label: t('finalRegions.promotedBy'), value: region.promoted_by },
            { label: t('finalRegions.promotedAt'), value: region.promoted_at.slice(0, 19).replace('T', ' ') },
            { label: t('finalRegions.createdAt'), value: region.created_at.slice(0, 19).replace('T', ' ') },
          ]}
        />
      </div>

      <div className="card">
        <div className="card-title">{t('finalRegions.provenance')}</div>
        <KeyValuePanel
          entries={[
            { label: t('finalRegions.candidateId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.candidate_id}</code> },
            { label: t('finalRegions.resourceId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.resource_id}</code> },
            { label: t('finalRegions.batchId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.batch_id}</code> },
            { label: t('finalRegions.parseRunId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.parse_run_id}</code> },
            { label: t('finalRegions.generationRunId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.generation_run_id}</code> },
            { label: t('finalRegions.sourceFileId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.source_file_id}</code> },
            { label: t('finalRegions.sourceRawLabelId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{region.source_raw_label_id}</code> },
          ]}
        />
      </div>

      <div className="card">
        <div className="card-title">{t('finalRegions.promotionRecords')}</div>
        {loading && <LoadingState text={t('finalRegions.loadingRecords')} />}
        {error && <ErrorState error={error} />}
        {prov && prov.promotion_records.length === 0 && <EmptyState text={t('finalRegions.emptyRecords')} />}
        {prov && prov.promotion_records.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {prov.promotion_records.map((rec) => (
              <div key={rec.id} style={{ padding: '12px', background: '#fafbfc', borderRadius: 4, border: '1px solid #e6e8ec' }}>
                <KeyValuePanel
                  entries={[
                    { label: t('finalRegions.recordId'), value: <code className="text-mono" style={{ fontSize: 11 }}>{rec.id}</code> },
                    { label: t('common.status'), value: <StatusBadge status={rec.status} /> },
                    { label: t('finalRegions.promotedBy'), value: rec.promoted_by },
                    { label: t('finalRegions.reason'), value: rec.reason },
                    { label: t('finalRegions.errorMessage'), value: rec.error_message ? <span style={{ color: '#cf1322' }}>{rec.error_message}</span> : null },
                    { label: t('finalRegions.time'), value: rec.created_at.slice(0, 19).replace('T', ' ') },
                  ]}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function FinalRegionsPage() {
  const [selected, setSelected] = useState<FinalBrainRegion | null>(null)
  const [keyword, setKeyword] = useState('')
  const [kwInput, setKwInput] = useState('')
  const [laterality, setLaterality] = useState('')
  const [granLevel, setGranLevel] = useState('')
  const [status, setStatus] = useState('')

  if (selected) {
    return <FinalRegionDetail region={selected} onBack={() => setSelected(null)} />
  }

  const filters = {
    keyword: keyword || undefined,
    laterality: laterality || undefined,
    granularity_level: granLevel || undefined,
    status: status || undefined,
    limit: 100,
    offset: 0,
  }

  return <FinalRegionList
    filters={filters}
    kwInput={kwInput}
    setKwInput={setKwInput}
    setKeyword={setKeyword}
    laterality={laterality}
    setLaterality={setLaterality}
    granLevel={granLevel}
    setGranLevel={setGranLevel}
    status={status}
    setStatus={setStatus}
    onSelect={setSelected}
  />
}

interface ListProps {
  filters: Record<string, string | number | undefined>
  kwInput: string
  setKwInput: (v: string) => void
  setKeyword: (v: string) => void
  laterality: string
  setLaterality: (v: string) => void
  granLevel: string
  setGranLevel: (v: string) => void
  status: string
  setStatus: (v: string) => void
  onSelect: (r: FinalBrainRegion) => void
}

function FinalRegionList({
  filters, kwInput, setKwInput, setKeyword,
  laterality, setLaterality, granLevel, setGranLevel,
  status, setStatus, onSelect,
}: ListProps) {
  const { t } = useI18n()
  const { data, loading, error } = useData(
    () => fetchFinalRegions(filters as Parameters<typeof fetchFinalRegions>[0]),
    [JSON.stringify(filters)],
  )

  const listColumns: Column<FinalBrainRegion>[] = useMemo(() => [
    { key: 'raw_name', header: t('finalRegions.rawName'), render: r => <strong>{r.raw_name}</strong> },
    { key: 'en_name', header: t('common.enName'), render: r => r.en_name ?? '—' },
    { key: 'cn_name', header: t('common.cnName'), render: r => r.cn_name ?? '—' },
    { key: 'laterality', header: t('common.laterality'), render: r => <StatusBadge status={r.laterality} /> },
    { key: 'source_atlas', header: t('finalRegions.atlas') },
    { key: 'source_version', header: t('common.version') },
    { key: 'granularity_level', header: t('finalRegions.granularityLevel') },
    { key: 'granularity_family', header: t('finalRegions.granularityFamily') },
    { key: 'status', header: t('common.status'), render: r => <StatusBadge status={r.status} /> },
    { key: 'promoted_by', header: t('finalRegions.promotedBy') },
    { key: 'promoted_at', header: t('finalRegions.promotedAt'), render: r => r.promoted_at.slice(0, 10) },
  ], [t])

  return (
    <div>
      <PageHeader title={t('finalRegions.title')} description={t('finalRegions.description')} />
      <div className="card">
        <div className="filter-bar">
          <input
            className="filter-input"
            placeholder={t('finalRegions.keywordPlaceholder')}
            value={kwInput}
            onChange={e => setKwInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && setKeyword(kwInput.trim())}
          />
          <button className="btn" onClick={() => setKeyword(kwInput.trim())}>{t('common.search')}</button>
          <select className="filter-select" value={laterality} onChange={e => setLaterality(e.target.value)}>
            <option value="">{t('finalRegions.allLaterality')}</option>
            {LATERALITIES.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
          <select className="filter-select" value={granLevel} onChange={e => setGranLevel(e.target.value)}>
            <option value="">{t('finalRegions.allGranularity')}</option>
            {GRANULARITY_LEVELS.map(g => <option key={g} value={g}>{g}</option>)}
          </select>
          <select className="filter-select" value={status} onChange={e => setStatus(e.target.value)}>
            <option value="">{t('finalRegions.allStatus')}</option>
            <option value="active">active</option>
            <option value="archived">archived</option>
          </select>
        </div>
        <DataTable
          columns={listColumns}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          total={data?.total}
          getKey={r => r.id}
          onRowClick={onSelect}
          emptyText={t('finalRegions.emptyList')}
        />
        {!loading && !error && data && data.items.length > 0 && (
          <div className="table-footer" style={{ color: '#1677ff', fontSize: 12 }}>
            {t('finalRegions.clickHint')}
          </div>
        )}
      </div>
    </div>
  )
}
