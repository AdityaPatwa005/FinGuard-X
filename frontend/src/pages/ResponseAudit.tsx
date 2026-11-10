import { useState } from 'react'
import type { IncidentDetail, IncidentList, OutboxHealth, RuleEvaluation } from '../api'
import { useApiResource } from '../useApiResource'
import { ApiState, DataBanner } from '../components/DataStates'
import { displayLabel, formatOpsDate } from '../format'

export default function ResponseAudit({ onNavigate }: { onNavigate: (page: string) => void }) {
  const health = useApiResource<OutboxHealth>('/operations/outbox/health', 0, 30_000)
  const evaluations = useApiResource<{ items: RuleEvaluation[]; total: number }>('/rule-evaluations/recent?limit=50&offset=0')
  const incidents = useApiResource<IncidentList>('/incidents?limit=30&offset=0')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selectedSummary = incidents.data?.items.find(item => item.id === selectedId) ?? incidents.data?.items[0] ?? null
  const detail = useApiResource<IncidentDetail>(selectedSummary ? `/incidents/${selectedSummary.id}` : null)

  return <div className="ops-page">
    <DataBanner title="Operational state and persisted audit records">Outbox counts describe stored processing states. The UI does not start workers or perform automated response actions.</DataBanner>
    <section className="panel ops-panel"><div className="panel-heading"><div><h2>Outbox processing health</h2><p>Transactional event delivery status · payloads and internal error details are not exposed</p></div><button type="button" className="text-button" onClick={health.retry}>Refresh</button></div>
      {health.error || (health.loading && !health.data) ? <ApiState loading={health.loading} error={health.error} retry={health.retry} /> : health.data && <><div className="outbox-health-head"><span className={`system-status ${health.data.status === 'HEALTHY' ? 'api-status-connected' : 'api-status-offline'}`}><span className="status-dot" />{displayLabel(health.data.status)}</span><span className="ops-muted">{health.data.note}</span></div><div className="ops-metrics"><article><span>Pending</span><strong>{health.data.pending_count}</strong><small>Oldest · {formatOpsDate(health.data.oldest_pending_at)}</small></article><article><span>Processing</span><strong>{health.data.processing_count}</strong><small>Rows currently claimed</small></article><article><span>Processed</span><strong>{health.data.processed_count}</strong><small>Latest · {formatOpsDate(health.data.last_processed_at)}</small></article><article className={health.data.failed_count ? 'attention' : ''}><span>Failed</span><strong>{health.data.failed_count}</strong><small>Oldest · {formatOpsDate(health.data.oldest_failed_at)}</small></article></div></>}
    </section>

    <div className="audit-grid"><section className="panel ops-panel"><div className="panel-heading"><div><h2>Rule evaluation audit</h2><p>Latest persisted outcomes · includes negative and not-evaluated results</p></div><button type="button" className="text-button" onClick={evaluations.retry}>Refresh</button></div>
      {evaluations.error || (evaluations.loading && !evaluations.data) ? <ApiState loading={evaluations.loading} error={evaluations.error} retry={evaluations.retry} /> : evaluations.data?.items.length ? <div className="audit-list">{evaluations.data.items.slice(0, 20).map(row => <article key={row.id}><span className={`outcome-pill ${row.outcome.toLowerCase()}`}>{displayLabel(row.outcome)}</span><div><strong>{row.rule_name}</strong><small>{row.rule_id} · {row.transaction_id.slice(0, 8).toUpperCase()} · {formatOpsDate(row.detected_at)}</small>{row.outcome === 'NOT_EVALUATED' && row.limitation && <p>{row.limitation}</p>}</div></article>)}</div> : <ApiState loading={false} error={null} empty={<><strong>No evaluation audit rows</strong><span>Persisted detection outcomes will appear here after event processing.</span></>} />}
    </section>

    <section className="panel ops-panel"><div className="panel-heading"><div><h2>Incident lifecycle audit</h2><p>Persisted status changes and analyst notes</p></div><button type="button" className="text-button" onClick={incidents.retry}>Refresh</button></div>
      {incidents.error || (incidents.loading && !incidents.data) ? <ApiState loading={incidents.loading} error={incidents.error} retry={incidents.retry} /> : incidents.data?.items.length ? <><div className="audit-incident-list">{incidents.data.items.map(item => <button type="button" key={item.id} onClick={() => setSelectedId(item.id)} className={selectedSummary?.id === item.id ? 'selected' : ''}><strong>{item.title}</strong><span>{item.id.slice(0, 8).toUpperCase()} · {displayLabel(item.status)} · {displayLabel(item.risk_band)}</span></button>)}</div>{detail.error || (detail.loading && !detail.data) ? <ApiState loading={detail.loading} error={detail.error} retry={detail.retry} /> : detail.data && <div className="audit-timeline"><div className="audit-timeline-head"><strong>Selected incident history</strong><button type="button" className="text-button" onClick={() => onNavigate('Investigation Center')}>Open investigation</button></div>{detail.data.timeline.map(entry => <article key={entry.id}><time>{formatOpsDate(entry.changed_at)}</time><strong>{entry.from_status === entry.to_status ? 'Analyst note' : `${displayLabel(entry.from_status ?? 'OPEN')} → ${displayLabel(entry.to_status)}`}</strong>{entry.note && <p>{entry.note}</p>}{entry.actor_identifier && <small>{entry.actor_identifier}</small>}</article>)}</div>}</> : <ApiState loading={false} error={null} empty={<><strong>No incidents to audit</strong><span>No persisted incident lifecycle records exist yet.</span></>} />}
    </section></div>

    <section className="panel ops-panel response-boundary"><div><span className="data-scope-tag">AVAILABLE RESPONSE</span><h2>Analyst workflow only</h2><p>Incident status transitions and audit notes are supported in Investigation Center. FinGuard X does not block transactions, lock accounts, move funds or connect to external payment systems.</p></div><button type="button" onClick={() => onNavigate('Investigation Center')}>Open Investigation Center</button></section>
  </div>
}
