import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useApiResource } from './useApiResource'
import LiveMonitoring from './pages/LiveMonitoring'
import Intelligence from './pages/Intelligence'
import GeospatialIntelligence from './pages/GeospatialIntelligence'
import ResponseAudit from './pages/ResponseAudit'
import './App.css'
import {
  apiRequest,
  getApiConfigurationError,
  type DashboardSummary,
  type DetectionEvidence,
  type IncidentDetail as IncidentDetailRecord,
  type IncidentListItem,
  type IncidentStatus,
  type RecentDetection,
  type RecentTransaction,
  type RiskBand,
} from './api'

type SortKey = 'time' | 'amount' | 'risk'
type SortDirection = 'asc' | 'desc'
type CaseSort = 'newest' | 'oldest' | 'risk-high' | 'risk-low'

const navigation = [
  { name: 'Command Center', icon: '⌂' },
  { name: 'Live Monitoring', icon: '◉' },
  { name: 'Intelligence', icon: '⌁' },
  { name: 'Geospatial Intelligence', icon: '◎' },
  { name: 'Investigation Center', icon: '⌕' },
  { name: 'Response & Audit', icon: '↗' },
]

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
  }).format(new Date(value)) + ' UTC'
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC',
  }).format(new Date(value)) + ' UTC'
}

function formatMoney(amount: string | number, currency: string) {
  const raw = String(amount)
  const negative = raw.startsWith('-')
  const unsigned = negative ? raw.slice(1) : raw
  const [wholePart, fractionPart = ''] = unsigned.split('.')
  if (!/^\d+$/.test(wholePart)) return `${raw} ${currency}`
  const whole = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(BigInt(wholePart))
  const fraction = fractionPart.padEnd(2, '0').slice(0, 2)
  const currencyPart = new Intl.NumberFormat('en-IN', { style: 'currency', currency }).formatToParts(0).find(part => part.type === 'currency')?.value ?? currency
  return `${negative ? '-' : ''}${currencyPart}${whole}.${fraction}`
}

function humanStatus(status: string) {
  return status.charAt(0) + status.slice(1).toLowerCase()
}

function riskLabel(band: RiskBand | null) {
  return band ? band.charAt(0) + band.slice(1).toLowerCase() : 'Unscored'
}

function formatEvidenceValue(evidence: DetectionEvidence) {
  const value = typeof evidence.value === 'boolean' ? (evidence.value ? 'Yes' : 'No') : String(evidence.value)
  return evidence.unit ? `${value} ${evidence.unit}` : value
}

function Icon({ children }: { children: ReactNode }) { return <span className="nav-icon">{children}</span> }

function Sidebar({ active, onSelect }: { active: string; onSelect: (name: string) => void }) {
  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark">F<i /></div><div><strong>FINGUARD <b>X</b></strong><small>FINANCIAL CYBER INTELLIGENCE</small></div></div>
    <div className="workspace-label">OPERATIONS</div>
    <nav aria-label="Main navigation">{navigation.map((item, index) => <button type="button" key={item.name} className={`nav-item ${active === item.name ? 'active' : ''}`} onClick={() => onSelect(item.name)} aria-current={active === item.name ? 'page' : undefined}><Icon>{item.icon}</Icon><span>{item.name}</span>{index === 1 && <span className="nav-live" />}</button>)}</nav>
    <div className="sidebar-bottom"><div className="analyst-avatar">—</div><div className="analyst-info"><strong>Analyst workspace</strong><span>Authentication not configured</span></div></div>
  </aside>
}

function MetricCard({ label, value, note, icon, tone }: { label: string; value: string; note: string; icon: string; tone: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}>{icon}</span></div><div className="metric-value">{value}</div><div className="metric-foot"><span>{note}</span></div></article>
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="api-state api-error" role="alert"><strong>Backend data unavailable</strong><span>{message}</span><button type="button" onClick={onRetry}>Retry</button></div>
}

function LoadingState({ label = 'Loading persisted data…' }: { label?: string }) {
  return <div className="api-state" role="status"><span className="loading-mark" />{label}</div>
}

function RiskDistribution({ summary }: { summary: DashboardSummary }) {
  const items = summary.risk_distribution
  const total = summary.risk_distribution_total
  const colors: Record<RiskBand, string> = { LOW: '#49bfb4', GUARDED: '#548ea0', ELEVATED: '#d4a456', CRITICAL: '#bf625e' }
  let cumulative = 0
  const stops = items.map(item => {
    const start = total ? cumulative / total * 100 : 0
    cumulative += item.count
    const end = total ? cumulative / total * 100 : 0
    return `${colors[item.band]} ${start}% ${end}%`
  })
  const gradient = total ? `conic-gradient(${stops.join(', ')})` : 'conic-gradient(#243139 0 100%)'
  return <section className="panel risk-panel"><div className="panel-heading"><div><h2>Incident risk distribution</h2><p>Persisted incidents · all statuses</p></div><span className="data-scope-tag">DATABASE</span></div>
    <div className="risk-content"><div className="donut-wrap"><div className="donut" style={{ background: gradient }}><div className="donut-hole"><strong>{total.toLocaleString()}</strong><span>INCIDENTS</span></div></div></div><div className="risk-legend">{items.map(item => <div className="risk-row" key={item.band}><span className={`legend-dot ${item.band.toLowerCase()}`} /><span className="risk-label">{riskLabel(item.band)}</span><strong>{item.count.toLocaleString()}</strong><span className="risk-percent">{total ? `${Math.round(item.count / total * 100)}%` : '0%'}</span></div>)}</div></div>
    <div className="risk-note"><span className="status-dot" /> Current persisted incident scores · not transaction-level probabilities</div>
  </section>
}

function DetectionFeed({ detections, loading, error, retry }: { detections: RecentDetection[] | null; loading: boolean; error: string | null; retry: () => void }) {
  return <section className="panel signal-panel"><div className="panel-heading"><div><h2>Recent triggered detections</h2><p>Persisted rule results · outbox records excluded</p></div><button type="button" className="text-button" onClick={retry}>Refresh</button></div>
    {error ? <ErrorState message={error} onRetry={retry} /> : loading && !detections ? <LoadingState label="Loading detection feed…" /> : detections?.length ? <div className="detection-feed">{detections.slice(0, 6).map(detection => <article className="detection-feed-item" key={detection.id}><div className="detection-feed-top"><strong>{detection.rule_name}</strong><span className={`case-severity ${detection.severity.toLowerCase()}`}>{detection.severity}</span></div><p>{detection.explanation}</p><div><span>{detection.transaction_amount ? formatMoney(detection.transaction_amount, detection.currency) : ''}</span><time>{formatTime(detection.detected_at)}</time></div></article>)}</div> : <div className="empty-events" role="status"><strong>No triggered detections</strong><span>Completed transfer evaluations have not produced a triggered rule result yet.</span></div>}
  </section>
}

type TransactionSortKey = SortKey

function compareAmount(left: string, right: string) {
  const toMinorUnits = (value: string) => {
    const [whole, fraction = ''] = value.split('.')
    return BigInt(whole || '0') * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2))
  }
  return toMinorUnits(left) < toMinorUnits(right) ? -1 : toMinorUnits(left) > toMinorUnits(right) ? 1 : 0
}

function EventsTable({ rows, loading, error, retry, selectedId, onSelect }: {
  rows: RecentTransaction[] | null; loading: boolean; error: string | null; retry: () => void
  selectedId: string | null; onSelect: (row: RecentTransaction) => void
}) {
  const [statusFilter, setStatusFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState<RiskBand | ''>('')
  const [sortKey, setSortKey] = useState<TransactionSortKey>('time')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const allRows = useMemo(() => rows ?? [], [rows])
  const filtered = useMemo(() => {
    const matches = allRows.filter(row => (!statusFilter || row.status === statusFilter) && (!riskFilter || row.risk_band === riskFilter))
    const multiplier = sortDirection === 'asc' ? 1 : -1
    return matches.sort((a, b) => {
      const result = sortKey === 'time' ? a.created_at.localeCompare(b.created_at)
        : sortKey === 'amount' ? compareAmount(a.amount, b.amount)
          : (a.risk_score ?? -1) - (b.risk_score ?? -1)
      return result * multiplier
    })
  }, [allRows, statusFilter, riskFilter, sortKey, sortDirection])
  const setSort = (key: TransactionSortKey) => {
    if (key === sortKey) setSortDirection(value => value === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDirection(key === 'time' ? 'desc' : 'asc') }
  }
  const sortHeader = (key: TransactionSortKey, label: string) => <button type="button" className="table-sort" onClick={() => setSort(key)} aria-pressed={sortKey === key}>{label}{sortKey === key ? sortDirection === 'asc' ? ' ↑' : ' ↓' : ''}</button>
  const activeFilters = Boolean(statusFilter || riskFilter)
  return <section className="panel events-panel"><div className="panel-heading"><div><h2>Recent transaction activity</h2><p>Persisted FinBank Simulator transactions · no blocked decisions are recorded by the simulator</p></div><button type="button" className="text-button" onClick={retry}>Refresh</button></div>
    <div className="table-controls"><label>Status <select aria-label="Filter transactions by status" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}><option value="">All statuses</option><option value="COMPLETED">Completed</option><option value="PENDING">Pending</option><option value="FAILED">Failed</option></select></label><label>Risk band <select aria-label="Filter transactions by risk band" value={riskFilter} onChange={event => setRiskFilter(event.target.value as RiskBand | '')}><option value="">All risk bands</option>{(['LOW', 'GUARDED', 'ELEVATED', 'CRITICAL'] as RiskBand[]).map(band => <option key={band} value={band}>{riskLabel(band)}</option>)}</select></label>{activeFilters && <><span className="active-filter-indicator" role="status">Filters active · {filtered.length} of {allRows.length} transactions</span><button type="button" className="clear-filters" onClick={() => { setStatusFilter(''); setRiskFilter('') }}>Clear all filters</button></>}</div>
    {error ? <ErrorState message={error} onRetry={retry} /> : loading && !rows ? <LoadingState label="Loading recent transactions…" /> : <><div className="table-scroll"><table><thead><tr><th>{sortHeader('time', 'TRANSACTION / TIME')}</th><th>TYPE</th><th>ACCOUNTS</th><th>{sortHeader('amount', 'AMOUNT')}</th><th>{sortHeader('risk', 'INCIDENT RISK')}</th><th>STATUS</th></tr></thead><tbody>{filtered.map(row => <tr key={row.id} className={`event-row ${selectedId === row.id ? 'selected' : ''}`} onClick={() => onSelect(row)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(row) } }} tabIndex={0} aria-label={`Open transaction ${row.id}, ${row.transaction_type}, ${row.status}`} aria-selected={selectedId === row.id}><td><strong className="event-id">{row.id.slice(0, 8).toUpperCase()}</strong><span className="cell-sub">{formatTime(row.created_at)}</span></td><td>{humanStatus(row.transaction_type)}</td><td>{row.sender_account ?? 'Funding pool'} → {row.receiver_account}</td><td className="amount">{formatMoney(row.amount, row.currency)}</td><td>{row.risk_band ? <div className="score"><strong>{row.risk_score}</strong><span className={`risk-level ${row.risk_band.toLowerCase()}`}>{riskLabel(row.risk_band)}</span></div> : <span className="muted-cell">No correlated incident</span>}</td><td><span className={`badge ${row.status.toLowerCase()}`}>{humanStatus(row.status)}</span></td></tr>)}</tbody></table>{filtered.length === 0 && <div className="empty-events" role="status"><strong>No matching transactions</strong><span>{activeFilters ? 'Adjust or clear the selected filters.' : 'No transaction records are available yet.'}</span></div>}</div><div className="table-footer"><span>Showing {filtered.length} of {allRows.length} loaded transactions</span><span>Recent API limit: 100</span></div></>}
  </section>
}

function DetailField({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="detail-field"><span>{label}</span><strong className={mono ? 'mono' : ''}>{value}</strong></div>
}

function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="drawer-section"><h3>{title}</h3>{children}</section>
}

function TransactionDrawer({ transaction, onClose }: { transaction: RecentTransaction; onClose: () => void }) {
  return <><button className="drawer-backdrop" aria-label="Close transaction details" onClick={onClose} /><aside className="investigation-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
    <header className="drawer-header"><div><span className="drawer-kicker">PERSISTED TRANSACTION <i>·</i> <b>SIMULATOR DATA</b></span><h2 id="drawer-title">{transaction.id}</h2><p>{humanStatus(transaction.transaction_type)}</p></div><button className="drawer-close" autoFocus onClick={onClose} aria-label="Close transaction details">×</button></header>
    <div className="drawer-scroll"><div className="drawer-synthetic-note"><span className="demo-icon">i</span><span>This record was generated by the synthetic FinBank Simulator and persisted by the connected backend.</span></div>
      <DrawerSection title="Transaction overview"><div className="detail-grid"><DetailField label="Transaction ID" value={transaction.id} mono /><DetailField label="Type" value={humanStatus(transaction.transaction_type)} /><DetailField label="Amount" value={formatMoney(transaction.amount, transaction.currency)} mono /><DetailField label="Timestamp" value={formatDate(transaction.created_at)} /><DetailField label="Simulator status" value={humanStatus(transaction.status)} /><DetailField label="Correlated incident risk" value={transaction.risk_band ? `${transaction.risk_score} / 100 · ${riskLabel(transaction.risk_band)}` : 'No correlated incident'} /></div></DrawerSection>
      <DrawerSection title="Account context"><div className="detail-grid"><DetailField label="Sender account" value={transaction.sender_account ?? 'Simulator funding pool'} mono /><DetailField label="Receiver account" value={transaction.receiver_account} mono /><DetailField label="Currency" value={transaction.currency} /></div><p className="ip-note">The simulator does not currently persist device, session, channel, or physical location context.</p></DrawerSection>
      <DrawerSection title="Triggered rule evidence">{transaction.detections.length ? <ul className="evidence-list">{transaction.detections.map(detection => <li key={detection.id}><span className="evidence-mark">!</span><div><strong>{detection.rule_name}</strong><p>{detection.explanation}</p><ul className="evidence-values">{detection.evidence.map((item, index) => <li key={`${detection.id}-${item.name}-${index}`}>{item.name.replaceAll('_', ' ')}: {formatEvidenceValue(item)}</li>)}</ul></div></li>)}</ul> : <div className="empty-events"><strong>No triggered rules</strong><span>This transaction has no persisted triggered rule result.</span></div>}</DrawerSection>
      <DrawerSection title="Record timeline"><ol className="event-timeline"><li className="current"><span className="timeline-time">{formatDate(transaction.created_at)}</span><strong>Transaction persisted</strong><p>The simulator recorded this {transaction.transaction_type.toLowerCase()} transaction.</p></li>{transaction.detections.map(detection => <li key={detection.id}><span className="timeline-time">{formatDate(detection.detected_at)}</span><strong>{detection.rule_name}</strong><p>{detection.explanation}</p></li>)}</ol></DrawerSection>
    </div>
  </aside></>
}

function CommandCenter() {
  const summary = useApiResource<DashboardSummary>('/dashboard/summary')
  const transactions = useApiResource<RecentTransaction[]>('/transactions/recent?limit=100')
  const detections = useApiResource<RecentDetection[]>('/detections/recent?limit=20')
  const [selected, setSelected] = useState<RecentTransaction | null>(null)
  useEffect(() => {
    if (!selected) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelected(null) }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [selected])

  return <>
    <div className="demo-banner"><span className="demo-icon">i</span><span><strong>Connected simulator environment</strong> Values below come from persisted API records. Source activity is synthetic; no external bank or real-time blocking system is connected.</span><span className="demo-tag">SIMULATOR DATA</span></div>
    {summary.error ? <ErrorState message={summary.error} onRetry={summary.retry} /> : summary.loading && !summary.data ? <LoadingState label="Loading dashboard summary…" /> : summary.data && <section className="metrics-grid"><MetricCard label="Transactions monitored · 24h" value={summary.data.transactions_monitored.toLocaleString()} note="Completed persisted transactions" icon="↗" tone="teal" /><MetricCard label="High-risk transactions · 24h" value={summary.data.high_risk_transactions.toLocaleString()} note="Linked to elevated or critical incidents" icon="△" tone="amber" /><MetricCard label="Active incidents" value={summary.data.active_incidents.toLocaleString()} note="Open or under investigation" icon="◈" tone="red" /><MetricCard label="Blocked transactions" value={summary.data.blocked_transactions === null ? 'N/A' : summary.data.blocked_transactions.toLocaleString()} note={summary.data.blocked_transactions_note} icon="⊘" tone="blue" /></section>}
    {summary.data && <div className="dashboard-grid"><RiskDistribution summary={summary.data} /><DetectionFeed detections={detections.data} loading={detections.loading} error={detections.error} retry={detections.retry} /></div>}
    {!summary.data && (summary.error || summary.loading) && <div className="dashboard-grid"><section className="panel risk-panel"><div className="panel-heading"><div><h2>Incident risk distribution</h2><p>Waiting for connected summary data</p></div></div></section><DetectionFeed detections={detections.data} loading={detections.loading} error={detections.error} retry={detections.retry} /></div>}
    <EventsTable rows={transactions.data} loading={transactions.loading} error={transactions.error} retry={transactions.retry} selectedId={selected?.id ?? null} onSelect={setSelected} />
    {selected && <TransactionDrawer transaction={selected} onClose={() => setSelected(null)} />}
  </>
}

const riskBands: RiskBand[] = ['CRITICAL', 'ELEVATED', 'GUARDED', 'LOW']
const incidentStatuses: IncidentStatus[] = ['OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED']
const riskOrder: Record<RiskBand, number> = { CRITICAL: 4, ELEVATED: 3, GUARDED: 2, LOW: 1 }

function CaseMetric({ label, value, caption, tone }: { label: string; value: number; caption: string; tone: string }) {
  return <article className="case-metric"><div className="case-metric-label"><span className={`case-metric-mark ${tone}`} />{label}</div><strong>{value.toLocaleString()}</strong><span>{caption}</span></article>
}

function IncidentDetail({ incident, onRefresh }: { incident: IncidentDetailRecord; onRefresh: () => void }) {
  const [nextStatus, setNextStatus] = useState<IncidentStatus>(incident.status)
  const [statusNote, setStatusNote] = useState('')
  const [noteDraft, setNoteDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const availableStatuses: IncidentStatus[] = incident.status === 'OPEN' ? ['INVESTIGATING', 'RESOLVED', 'DISMISSED']
    : incident.status === 'INVESTIGATING' ? ['RESOLVED', 'DISMISSED'] : []

  const updateStatus = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      await apiRequest<IncidentDetailRecord>(`/incidents/${incident.id}/status`, {
        method: 'PATCH', body: JSON.stringify({ status: nextStatus, note: statusNote.trim() || null }),
      })
      setStatusNote(''); onRefresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Status update failed.') }
    finally { setBusy(false) }
  }
  const addNote = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const note = noteDraft.trim()
    if (!note) return
    setBusy(true); setError(null)
    try {
      await apiRequest<IncidentDetailRecord>(`/incidents/${incident.id}/notes`, { method: 'POST', body: JSON.stringify({ note }) })
      setNoteDraft(''); onRefresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Note could not be saved.') }
    finally { setBusy(false) }
  }

  return <section className="case-detail-panel">
    <div className="case-detail-top"><div><span className="case-kicker">PERSISTED INCIDENT · {incident.id.slice(0, 8).toUpperCase()}</span><h2>{incident.title}</h2><span className="case-id">{incident.id}</span></div><span className={`case-severity ${incident.risk_band.toLowerCase()}`}>{riskLabel(incident.risk_band)}</span></div>
    <p className="case-description">{incident.risk_explanation}</p>
    <div className="case-status-line"><span className={`case-status ${incident.status.toLowerCase()}`}>{humanStatus(incident.status)}</span><span>Assigned analyst <strong>Not set up</strong></span><span className="detail-risk-score">Risk {incident.risk_score}/100</span></div>
    <div className="case-detail-section"><h3>Incident overview</h3><div className="case-overview-grid"><div><span>Primary account</span><strong>{incident.primary_account}</strong></div><div><span>Created</span><strong>{formatDate(incident.opened_at)}</strong></div><div><span>Last activity</span><strong>{formatDate(incident.last_activity_at)}</strong></div><div><span>Risk policy</span><strong>{incident.risk_policy_version}</strong></div></div></div>
    <div className="case-detail-section"><h3>Related transactions <span className="section-count">{incident.transactions.length}</span></h3>{incident.transactions.length ? <div className="case-chip-list">{incident.transactions.map(transaction => <span key={transaction.id}>{transaction.id.slice(0, 8).toUpperCase()} · {formatMoney(transaction.amount, transaction.currency)}</span>)}</div> : <p className="no-notes">No transaction records are linked.</p>}</div>
    <div className="case-detail-section"><h3>Triggered rule evidence <span className="section-count">{incident.detections.length}</span></h3>{incident.detections.length ? <div className="incident-evidence-list">{incident.detections.map(detection => <article key={detection.id}><div className="detection-feed-top"><strong>{detection.rule_name}</strong><span className={`case-severity ${detection.severity.toLowerCase()}`}>{detection.severity}</span></div><p>{detection.explanation}</p><small>{detection.rule_id} · v{detection.rule_version} · {formatDate(detection.detected_at)}</small><ul className="evidence-values">{detection.evidence.map((item, index) => <li key={`${detection.id}-${item.name}-${index}`}>{item.name.replaceAll('_', ' ')}: {formatEvidenceValue(item)}</li>)}</ul>{detection.limitation && <small>Limitation: {detection.limitation}</small>}</article>)}</div> : <p className="no-notes">No triggered rule evidence is attached.</p>}</div>
    <div className="case-detail-section"><h3>Risk contributions</h3>{incident.risk_evidence.length ? <div className="case-chip-list domains">{incident.risk_evidence.map((family, index) => <span key={`${family.family}-${index}`}>{family.family.replaceAll('_', ' ')} +{family.weight} · {family.rule_ids.length} rule(s)</span>)}</div> : <p className="no-notes">No weighted evidence families are available.</p>}</div>
    <div className="case-detail-section"><h3>Incident timeline</h3>{incident.timeline.length ? <ol className="case-timeline">{incident.timeline.map((entry, index) => <li key={entry.id}><span className="case-timeline-dot" /><time>{formatDate(entry.changed_at)}</time><strong>{entry.from_status === entry.to_status ? 'Analyst note' : `${humanStatus(entry.from_status ?? 'OPEN')} → ${humanStatus(entry.to_status)}`}</strong>{entry.note && <p>{entry.note}</p>}{entry.actor_identifier && <small>{entry.actor_identifier}</small>}{index < incident.timeline.length - 1 && <i className="case-timeline-line" />}</li>)}</ol> : <p className="no-notes">No lifecycle history recorded.</p>}</div>
    <div className="case-detail-section notes-section"><div className="notes-heading"><h3>Analyst notes</h3><span>PERSISTED</span></div>{incident.timeline.filter(entry => entry.note).length ? <ul className="analyst-notes">{incident.timeline.filter(entry => entry.note).map(entry => <li key={entry.id}><p>{entry.note}</p><small>{formatDate(entry.changed_at)} · {entry.actor_identifier ?? 'Actor unavailable'}</small></li>)}</ul> : <p className="no-notes">No notes recorded for this incident yet.</p>}<form className="note-form" onSubmit={addNote}><label htmlFor="incident-note">Add a note</label><textarea id="incident-note" value={noteDraft} onChange={event => setNoteDraft(event.target.value)} placeholder="Record an investigation observation…" rows={3} /><button type="submit" disabled={busy || !noteDraft.trim()}>Save note</button><small>Notes are appended to the incident audit timeline.</small></form></div>
    {availableStatuses.length > 0 && <div className="case-detail-section status-action-section"><h3>Update incident status</h3><form className="note-form" onSubmit={updateStatus}><label htmlFor="incident-status">New status</label><select id="incident-status" value={nextStatus} onChange={event => setNextStatus(event.target.value as IncidentStatus)}><option value={incident.status}>{humanStatus(incident.status)} (current)</option>{availableStatuses.map(value => <option value={value} key={value}>{humanStatus(value)}</option>)}</select><label htmlFor="status-note">Audit comment <span>(optional)</span></label><textarea id="status-note" value={statusNote} onChange={event => setStatusNote(event.target.value)} rows={2} maxLength={2000} placeholder="Reason for this status change…" /><button type="submit" disabled={busy || nextStatus === incident.status}>Update status</button></form></div>}
    {error && <div className="inline-api-error" role="alert">{error}</div>}
  </section>
}

function InvestigationCenter() {
  const [query, setQuery] = useState('')
  const [riskFilter, setRiskFilter] = useState<RiskBand | ''>('')
  const [statusFilter, setStatusFilter] = useState<IncidentStatus | ''>('')
  const [sort, setSort] = useState<CaseSort>('newest')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [summaryRefreshKey, setSummaryRefreshKey] = useState(0)
  const dashboard = useApiResource<DashboardSummary>('/dashboard/summary', summaryRefreshKey)
  const params = new URLSearchParams({ limit: '100', offset: '0' })
  if (statusFilter) params.set('status', statusFilter)
  if (riskFilter) params.set('risk_band', riskFilter)
  const incidents = useApiResource<{ items: IncidentListItem[]; total: number }>(`/incidents?${params.toString()}`, refreshKey)
  const details = useApiResource<IncidentDetailRecord>(selectedId ? `/incidents/${selectedId}` : null, refreshKey)
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return [...(incidents.data?.items ?? [])].filter(item => !normalized || item.id.toLowerCase().includes(normalized) || item.title.toLowerCase().includes(normalized)).sort((a, b) => {
      if (sort === 'newest') return b.opened_at.localeCompare(a.opened_at)
      if (sort === 'oldest') return a.opened_at.localeCompare(b.opened_at)
      const difference = riskOrder[b.risk_band] - riskOrder[a.risk_band]
      return sort === 'risk-high' ? difference || b.opened_at.localeCompare(a.opened_at) : -difference || a.opened_at.localeCompare(b.opened_at)
    })
  }, [incidents.data, query, sort])
  const hasFilters = Boolean(query.trim() || riskFilter || statusFilter)
  const clearFilters = () => { setQuery(''); setRiskFilter(''); setStatusFilter('') }
  const refreshDetails = () => { setRefreshKey(value => value + 1); setSummaryRefreshKey(value => value + 1) }
  return <div className="case-workspace">
    <div className="case-demo-strip"><span className="demo-icon">i</span><span><strong>Connected incident workspace</strong> Cases, rule evidence and analyst notes are read from or written to the configured backend.</span><span className="demo-tag">PERSISTED DATA</span></div>
    {dashboard.error ? <ErrorState message={dashboard.error} onRetry={dashboard.retry} /> : dashboard.loading && !dashboard.data ? <LoadingState label="Loading incident metrics…" /> : dashboard.data && <section className="case-metrics"><CaseMetric label="Open cases" value={dashboard.data.open_cases} caption="unresolved incidents" tone="teal" /><CaseMetric label="Critical cases" value={dashboard.data.critical_cases} caption="active critical risk band" tone="red" /><CaseMetric label="Awaiting review" value={dashboard.data.awaiting_review} caption="open incidents" tone="amber" /><CaseMetric label="Resolved cases" value={dashboard.data.resolved_cases} caption="resolved incidents" tone="blue" /></section>}
    <div className="case-work-area"><section className="case-queue panel"><div className="case-queue-heading"><div><h2>Incident queue</h2><p>{filtered.length} shown · {incidents.data?.total ?? 0} total persisted incidents</p></div><button type="button" className="text-button" onClick={incidents.retry}>Refresh</button></div>
      <div className="case-filters"><label className="case-search"><span aria-hidden="true">⌕</span><input aria-label="Search incidents by ID or rule name" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search incident ID or rule…" /></label><div className="case-filter-row"><label><span className="sr-only">Filter by risk band</span><select aria-label="Filter by risk band" value={riskFilter} onChange={event => setRiskFilter(event.target.value as RiskBand | '')}><option value="">All risk bands</option>{riskBands.map(value => <option key={value} value={value}>{riskLabel(value)}</option>)}</select></label><label><span className="sr-only">Filter by status</span><select aria-label="Filter by incident status" value={statusFilter} onChange={event => setStatusFilter(event.target.value as IncidentStatus | '')}><option value="">All statuses</option>{incidentStatuses.map(value => <option key={value} value={value}>{humanStatus(value)}</option>)}</select></label><label><span className="sr-only">Sort incidents</span><select aria-label="Sort incidents" value={sort} onChange={event => setSort(event.target.value as CaseSort)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="risk-high">Risk: high to low</option><option value="risk-low">Risk: low to high</option></select></label></div>
      {hasFilters && <div className="case-filter-status" role="status"><span>Filters active · {filtered.length} matches</span><button type="button" onClick={clearFilters}>Clear all filters</button></div>}</div>
      {incidents.error ? <ErrorState message={incidents.error} onRetry={incidents.retry} /> : incidents.loading && !incidents.data ? <LoadingState label="Loading incident queue…" /> : <div className="case-list">{filtered.length ? filtered.map(item => <button type="button" key={item.id} className={`case-list-item ${selectedId === item.id ? 'selected' : ''}`} onClick={() => setSelectedId(item.id)} aria-pressed={selectedId === item.id}><div className="case-list-top"><span className="case-id">{item.id.slice(0, 8).toUpperCase()}</span><span className={`case-severity ${item.risk_band.toLowerCase()}`}>{riskLabel(item.risk_band)}</span></div><strong>{item.title}</strong><div className="case-list-bottom"><span className={`case-status ${item.status.toLowerCase()}`}>{humanStatus(item.status)}</span><span>{item.primary_account}</span><time>{formatDate(item.opened_at)}</time></div><small>{item.detection_count} detections · {item.transaction_count} transactions · risk {item.risk_score}/100</small></button>) : <div className="case-empty"><span>⌕</span><strong>{hasFilters ? 'No matching incidents' : 'No incidents yet'}</strong><p>{hasFilters ? 'Adjust your search or filters to see more persisted incidents.' : 'No triggered rule evaluations have created incidents in the connected database.'}</p>{hasFilters && <button type="button" onClick={clearFilters}>Clear all filters</button>}</div>}</div>}
    </section>
    {selectedId ? details.error ? <section className="case-detail-empty panel"><ErrorState message={details.error} onRetry={details.retry} /></section> : details.loading && !details.data ? <section className="case-detail-empty panel"><LoadingState label="Loading incident details…" /></section> : details.data ? <IncidentDetail key={details.data.id} incident={details.data} onRefresh={refreshDetails} /> : null : <section className="case-detail-empty panel"><span className="case-empty-mark">⌕</span><h2>Select an incident</h2><p>Select a persisted incident to review its transactions, rule evidence, lifecycle history and analyst notes.</p></section>}
    </div>
  </div>
}

function App() {
  const [active, setActive] = useState('Command Center')
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'offline'>('checking')
  const isCommand = active === 'Command Center'
  const isInvestigationCenter = active === 'Investigation Center'
  const pageDescriptions: Record<string, string> = {
    'Command Center': 'Review persisted simulator transactions, rule detections and incident risk.',
    'Live Monitoring': 'Review recent persisted simulator activity with periodic API refresh.',
    Intelligence: 'Inspect configured detection rules, persisted outcomes and risk evidence.',
    'Geospatial Intelligence': 'Review location data availability without inferring physical position from transfers.',
    'Investigation Center': 'Review correlated incidents, inspect evidence and record auditable analyst notes.',
    'Response & Audit': 'Review outbox processing health and persisted incident and rule audit records.',
  }
  const pageContent = active === 'Command Center' ? <CommandCenter />
    : active === 'Live Monitoring' ? <LiveMonitoring />
      : active === 'Intelligence' ? <Intelligence />
        : active === 'Geospatial Intelligence' ? <GeospatialIntelligence />
          : active === 'Investigation Center' ? <InvestigationCenter />
            : <ResponseAudit onNavigate={setActive} />
  useEffect(() => {
    const controller = new AbortController()
    apiRequest<{ status: string }>('/health/database', { signal: controller.signal })
      .then(value => setApiStatus(value.status === 'healthy' ? 'connected' : 'offline'))
      .catch(() => { if (!controller.signal.aborted) setApiStatus('offline') })
    return () => controller.abort()
  }, [])
  const configurationError = getApiConfigurationError()
  const connectionLabel = configurationError ? 'API URL not configured' : apiStatus === 'connected' ? 'API connected' : apiStatus === 'checking' ? 'Checking API' : 'API unavailable'
  return <div className="app-shell"><Sidebar active={active} onSelect={setActive} /><main className="main-area"><header className="topbar"><div className="breadcrumbs"><span>Workspace</span><i>/</i><strong>{active}</strong></div><div className="header-actions"><label className="search"><span>⌕</span><input placeholder="Search persisted records…" aria-label="Search is available within each list" /><kbd>⌘ K</kbd></label><div className={`system-status api-status-${apiStatus}`}><span className="status-dot" />{connectionLabel}</div></div></header>
    <div className="content"><div className="page-heading"><div><div className="eyebrow">SECURITY OPERATIONS <span>•</span> {isInvestigationCenter ? 'INCIDENT MANAGEMENT' : isCommand ? 'CONNECTED OVERVIEW' : 'OPERATIONS WORKSPACE'}</div><h1>{active}</h1><p>{pageDescriptions[active]}</p></div><div className="heading-right"><div className="updated"><span className={`status-dot api-status-${apiStatus}`} />{connectionLabel}<i>·</i> PostgreSQL-backed API</div><span className="data-scope-tag">SYNTHETIC SOURCE</span></div></div>
    {configurationError ? <ErrorState message={configurationError} onRetry={() => window.location.reload()} /> : pageContent}
    <footer className="app-footer"><span>FINGUARD X <i>·</i> SECURITY OPERATIONS</span><span>Synthetic simulator data <i>·</i> PostgreSQL-backed detection pipeline</span></footer></div></main></div>
}

export default App
