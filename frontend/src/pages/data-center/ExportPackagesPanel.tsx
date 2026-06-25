import { useMemo, useState } from 'react'
import { type Column } from '../../components/DataTable'
import { CopyButton } from '../../components/CopyButton'
import { useData } from '../../hooks/useData'
import { useI18n } from '../../i18n-context'
import {
  listFinalKgExports,
  listFinalKgExportFiles,
  getFinalKgExportFileUrl,
  type FinalKgExportManifestRead,
  type FinalKgExportFileRead,
} from '../../api/endpoints'
import { DataCenterTableRegion } from './DataCenterTableRegion'

export function ExportPackagesPanel() {
  const { t } = useI18n()
  const [tick, setTick] = useState(0)
  const [selectedExportId, setSelectedExportId] = useState('')

  const { data, loading, error } = useData(() => listFinalKgExports(), [tick])

  const { data: filesData, loading: filesLoading, error: filesError } = useData(
    () => selectedExportId ? listFinalKgExportFiles(selectedExportId) : Promise.resolve({ export_id: '', files: [] }),
    [selectedExportId, tick],
  )

  const exportCols = useMemo<Column<FinalKgExportManifestRead>[]>(() => [
    { key: 'export_id', header: 'export_id', render: r => (
      <span className="pipeline-run-id-cell">
        <code>{r.export_id.slice(0, 12)}…</code>
        <CopyButton value={r.export_id} label="" />
      </span>
    ) },
    { key: 'created_at', header: 'created_at', render: r => r.created_at?.slice(0, 16).replace('T', ' ') ?? '—' },
    { key: 'formats', header: 'formats', render: r => (r.formats ?? []).join(', ') || '—' },
    { key: 'node_count', header: 'nodes', render: r => r.counts?.nodes ?? '—' },
    { key: 'edge_count', header: 'edges', render: r => r.counts?.edges ?? '—' },
  ], [])

  const fileCols = useMemo<Column<FinalKgExportFileRead>[]>(() => [
    { key: 'filename', header: 'filename' },
    { key: 'size_bytes', header: 'size', render: r => `${Math.round(r.size_bytes / 1024)} KB` },
    { key: 'modified_at', header: 'modified', render: r => r.modified_at?.slice(0, 16).replace('T', ' ') ?? '—' },
    {
      key: 'download_url',
      header: 'download',
      render: r => (
        <a href={getFinalKgExportFileUrl(r.export_id, r.filename)} target="_blank" rel="noreferrer">
          download
        </a>
      ),
    },
  ], [])

  return (
    <div className="data-center-panel">
      <div className="data-center-boundary data-center-boundary-export">
        {t('dataCenter.boundaryExport')}
      </div>
      <div className="data-center-filter-bar">
        <button type="button" className="btn" onClick={() => setTick(x => x + 1)}>{t('dataCenter.refresh')}</button>
        <a className="btn" href="#/llm-extraction?tab=finalExport">{t('dataCenter.openFinalExport')}</a>
      </div>

      <DataCenterTableRegion
        key="exports"
        items={data?.items ?? []}
        resetKeys={[tick]}
        columns={exportCols}
        loading={loading}
        error={error}
        emptyText={t('dataCenter.noData')}
        getKey={r => r.export_id}
        onRowClick={r => setSelectedExportId(r.export_id)}
      />

      {selectedExportId && (
        <div className="data-center-files-section">
          <h4 className="data-center-files-title">Files — {selectedExportId.slice(0, 12)}…</h4>
          <DataCenterTableRegion
            key={`files-${selectedExportId}`}
            items={filesData?.files ?? []}
            resetKeys={[selectedExportId, tick]}
            columns={fileCols}
            loading={filesLoading}
            error={filesError}
            emptyText={t('dataCenter.noData')}
            getKey={r => r.filename}
          />
        </div>
      )}
    </div>
  )
}
