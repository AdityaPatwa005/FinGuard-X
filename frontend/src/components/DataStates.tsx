import type { ReactNode } from 'react'
import { displayLabel } from '../format'

export function ApiState({
  loading,
  error,
  retry,
  empty,
}: {
  loading: boolean
  error: string | null
  retry?: () => void
  empty?: ReactNode
}) {
  if (error) return <div className="ops-state ops-error" role="alert"><strong>Backend data unavailable</strong><span>{error}</span>{retry && <button type="button" onClick={retry}>Retry</button>}</div>
  if (loading) return <div className="ops-state" role="status"><span className="loading-mark" />Loading persisted data…</div>
  if (empty) return <div className="ops-state ops-empty" role="status">{empty}</div>
  return null
}

export function DataBanner({ title, children, tag = 'PERSISTED DATA' }: { title: string; children: ReactNode; tag?: string }) {
  return <div className="ops-banner"><span className="demo-icon">i</span><div><strong>{title}</strong><span>{children}</span></div><span className="data-scope-tag">{tag}</span></div>
}

export function EvidenceList({ items }: { items: { name: string; value: string | number | boolean; unit: string | null }[] }) {
  if (!items.length) return <p className="ops-muted">No evidence values were persisted.</p>
  return <ul className="evidence-values">{items.map((item, index) => <li key={`${item.name}-${index}`}>{displayLabel(item.name)}: {typeof item.value === 'boolean' ? item.value ? 'Yes' : 'No' : item.value}{item.unit ? ` ${item.unit}` : ''}</li>)}</ul>
}
