import { useMemo, useState } from 'react'
import type { RecentDetection, RecentTransaction, RiskBand } from '../api'
import { useApiResource } from '../useApiResource'
import { ApiState, DataBanner, EvidenceList } from '../components/DataStates'
import { displayLabel, formatOpsDate, formatOpsMoney } from '../format'

const bands: RiskBand[] = ['CRITICAL', 'ELEVATED', 'GUARDED', 'LOW']

export default function LiveMonitoring() {
  const transactions = useApiResource<RecentTransaction[]>('/transactions/recent?limit=100', 0, 15_000)
  const detections = useApiResource<RecentDetection[]>('/detections/recent?limit=30', 0, 15_000)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [riskBand, setRiskBand] = useState<RiskBand | ''>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const rows = useMemo(() => transactions.data ?? [], [transactions.data])
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows.filter(row => (!status || row.status === status)
      && (!type || row.transaction_type === type)
      && (!riskBand || row.risk_band === riskBand)
      && (!needle || row.id.toLowerCase().includes(needle) || (row.sender_account ?? '').toLowerCase().includes(needle) || row.receiver_account.toLowerCase().includes(needle)))
  }, [rows, query, status, type, riskBand])
  const selected = rows.find(row => row.id === selectedId) ?? null

  const clearFilters = () => { setQuery(''); setStatus(''); setType(''); setRiskBand('') }
  const activeFilters = Boolean(query || status || type || riskBand)

  return <div className="ops-page">
    <DataBanner title="Persisted activity · refreshes every 15 seconds">This is periodic API polling, not a streaming connection. Transactions are synthetic simulator records.</DataBanner>
    <div className="ops-toolbar"><div className="ops-filters">
      <label>Search <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Transaction ID or masked account" /></label>
      <label>Status <select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option><option value="COMPLETED">Completed</option><option value="PENDING">Pending</option><option value="FAILED">Failed</option></select></label>
      <label>Type <select value={type} onChange={event => setType(event.target.value)}><option value="">All types</option><option value="TRANSFER">Transfer</option><option value="FUNDING">Funding</option></select></label>
      <label>Risk <select value={riskBand} onChange={event => setRiskBand(event.target.value as RiskBand | '')}><option value="">All bands</option>{bands.map(band => <option key={band} value={band}>{displayLabel(band)}</option>)}</select></label>
    </div><div className="ops-toolbar-actions"><span className="ops-muted">Latest 100 transactions</span><button type="button" className="text-button" onClick={() => { transactions.retry(); detections.retry() }}>Refresh now</button>{activeFilters && <button type="button" className="text-button" onClick={clearFilters}>Clear filters</button>}</div></div>

    <div className="monitor-grid">
      <section className="panel ops-panel"><div className="panel-heading"><div><h2>Transaction activity</h2><p>{filtered.length} shown · {rows.length} recent API records</p></div><span className="data-scope-tag">SIMULATOR</span></div>
        {transactions.error || (transactions.loading && !transactions.data) ? <ApiState loading={transactions.loading} error={transactions.error} retry={transactions.retry} /> : filtered.length === 0 ? <ApiState loading={false} error={null} empty={<><strong>{rows.length ? 'No matching transactions' : 'No transactions recorded'}</strong><span>{rows.length ? 'Adjust or clear the current filters.' : 'Completed simulator activity will appear here after it is persisted.'}</span></>} /> : <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>TRANSACTION</th><th>TYPE</th><th>ACCOUNTS</th><th>AMOUNT</th><th>RISK</th><th>STATUS</th></tr></thead><tbody>{filtered.map(row => <tr key={row.id} className={selectedId === row.id ? 'selected' : ''}>
          <td><button type="button" className="ops-row-link" onClick={() => setSelectedId(row.id)} aria-pressed={selectedId === row.id}>{row.id.slice(0, 8).toUpperCase()}</button><span className="ops-subline">{formatOpsDate(row.created_at)}</span></td>
          <td>{displayLabel(row.transaction_type)}</td><td>{row.sender_account ?? 'Funding pool'} → {row.receiver_account}</td><td>{formatOpsMoney(row.amount, row.currency)}</td>
          <td>{row.risk_band ? <span className={`risk-level ${row.risk_band.toLowerCase()}`}>{displayLabel(row.risk_band)} · {row.risk_score}</span> : <span className="ops-muted">Unscored</span>}</td><td><span className={`badge ${row.status.toLowerCase()}`}>{displayLabel(row.status)}</span></td>
        </tr>)}</tbody></table></div>}
      </section>

      <section className="panel ops-panel"><div className="panel-heading"><div><h2>Recent triggered detections</h2><p>Persisted rule results · outbox records excluded</p></div><span className="data-scope-tag">RULE ENGINE</span></div>
        {detections.error || (detections.loading && !detections.data) ? <ApiState loading={detections.loading} error={detections.error} retry={detections.retry} /> : detections.data?.length ? <div className="ops-detection-list">{detections.data.slice(0, 8).map(item => <article key={item.id}><div className="detection-feed-top"><strong>{item.rule_name}</strong><span className={`case-severity ${item.severity.toLowerCase()}`}>{item.severity}</span></div><p>{item.explanation}</p><small>{item.rule_id} · {formatOpsDate(item.detected_at)}</small></article>)}</div> : <ApiState loading={false} error={null} empty={<><strong>No triggered detections</strong><span>Evaluations may be negative or not evaluated; only triggered results appear in this feed.</span></>} />}
      </section>
    </div>

    <section className="panel ops-panel"><div className="panel-heading"><div><h2>Transaction inspection</h2><p>Selection shows persisted fields and rule evidence only</p></div><span className="data-scope-tag">READ ONLY</span></div>
      {selected ? <div className="inspect-grid"><div className="inspect-fields"><div><span>Transaction ID</span><strong className="mono">{selected.id}</strong></div><div><span>Timestamp</span><strong>{formatOpsDate(selected.created_at)}</strong></div><div><span>Type / status</span><strong>{displayLabel(selected.transaction_type)} · {displayLabel(selected.status)}</strong></div><div><span>Amount</span><strong>{formatOpsMoney(selected.amount, selected.currency)}</strong></div><div><span>Sender</span><strong>{selected.sender_account ?? 'Funding pool'}</strong></div><div><span>Receiver</span><strong>{selected.receiver_account}</strong></div></div><div><h3>Triggered evidence</h3>{selected.detections.length ? selected.detections.map(item => <article className="inspect-evidence" key={item.id}><strong>{item.rule_name}</strong><p>{item.explanation}</p><EvidenceList items={item.evidence} /></article>) : <div className="ops-empty-inline">No triggered rule results are linked to this transaction. This does not imply that all rules were evaluated.</div>}</div></div> : <div className="ops-empty-inline">Select a transaction row to inspect its persisted details.</div>}
      <p className="ops-footnote">Device, session, channel and physical location are not persisted in the current simulator transaction event.</p>
    </section>
  </div>
}
