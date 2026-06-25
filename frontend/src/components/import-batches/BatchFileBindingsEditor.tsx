import { ActionButton } from '../ActionButton'
import { useI18n } from '../../i18n-context'
import { emptyBinding, type FileBindingRow } from './batchModalUtils'

export function BatchFileBindingsEditor({
  resourceId,
  parserKey,
  bindings,
  fileRoles,
  onChange,
  formatRoleLabel,
}: {
  resourceId: string
  parserKey: string
  bindings: FileBindingRow[]
  fileRoles: string[]
  onChange: (rows: FileBindingRow[]) => void
  formatRoleLabel: (role: string) => string
}) {
  const { t } = useI18n()

  function updateRow(index: number, patch: Partial<FileBindingRow>) {
    onChange(bindings.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }

  function removeRow(index: number) {
    onChange(bindings.filter((_, i) => i !== index))
  }

  function addRow() {
    onChange([...bindings, emptyBinding()])
  }

  return (
    <div className="batch-file-binding-editor">
      <div className="import-batch-section-label">{t('pipeline.fileBindingEditor')}</div>
      <p className="batch-create-hint">{t('pipeline.batchCrudHint')}</p>
      <div className="batch-binding-table-wrap">
        <table className="batch-binding-table">
          <thead>
            <tr>
              <th>{t('batches.fileId')}</th>
              <th>{t('batches.fileRoleInBatch')}</th>
              <th>{t('batches.orderIndex')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {bindings.map((b, i) => (
              <tr key={i} className="batch-binding-row">
                <td>
                  <input
                    className="form-input"
                    value={b.file_id}
                    placeholder={resourceId.slice(0, 8)}
                    onChange={e => updateRow(i, { file_id: e.target.value })}
                  />
                </td>
                <td>
                  <select
                    className="form-select"
                    value={b.file_role_in_batch}
                    onChange={e => updateRow(i, { file_role_in_batch: e.target.value })}
                  >
                    {fileRoles.map(r => (
                      <option key={r} value={r}>{formatRoleLabel(r)}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="form-input"
                    type="number"
                    min={0}
                    style={{ width: 70 }}
                    value={b.sort_order}
                    onChange={e => updateRow(i, { sort_order: Number(e.target.value) })}
                  />
                </td>
                <td className="batch-binding-actions">
                  <ActionButton label={t('pipeline.detachFile')} variant="default" onClick={() => removeRow(i)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ActionButton label={t('pipeline.attachFile')} variant="default" onClick={addRow} />
      {parserKey && (
        <div className="batch-create-hint">parser_key: {parserKey}</div>
      )}
    </div>
  )
}
