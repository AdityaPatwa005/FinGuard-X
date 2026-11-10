import { useMemo, useState } from 'react'
import type { IncidentDetail, RuleCatalogItem, RuleEvaluation } from '../api'
import { useApiResource } from '../useApiResource'
import { ApiState, DataBanner, EvidenceList } from '../components/DataStates'
import { displayLabel, formatOpsDate, formatOpsMoney } from '../format'

type Outcome = RuleEvaluation['outcome'] | ''

export default function Intelligence() {
  const catalogue = useApiResource<RuleCatalogItem[]>('/rules/catalogue')
  const [outcome, setOutcome] = useState<Outcome>('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const query = new URLSearchParams({ limit: '100', offset: '0' })
  if (outcome) query.set('outcome', outcome)
  const evaluations = useApiResource<{ items: RuleEvaluation[]; total: number }>(`/rule-evaluations/recent?${query.toString()}`, refreshKey)
  const rows = useMemo(() => evaluations.data?.items ?? [], [evaluations.data])
  const selected = rows.find(row => row.id === selectedId) ?? rows[0] ?? null
  const incident = useApiResource<IncidentDetail>(selected?.incident_id ? `/incidents/${selected.incident_id}` : null, refreshKey)

  const catalogueById = useMemo(() => new Map((catalogue.data ?? []).map(rule => [rule.rule_id, rule])), [catalogue.data])

  return <div className="ops-page">
    <DataBanner title="Explainable rule intelligence">Rules are deterministic indicators, not confirmed fraud findings. Default thresholds are engineering starting points and are not production-calibrated.</DataBanner>
    <section className="panel ops-panel"><div className="panel-heading"><div><h2>Active rule catalogue</h2><p>Definitions and effective configured thresholds</p></div><button type="button" className="text-button" onClick={catalogue.retry}>Refresh</button></div>
      {catalogue.error || (catalogue.loading && !catalogue.data) ? <ApiState loading={catalogue.loading} error={catalogue.error} retry={catalogue.retry} /> : catalogue.data?.length ? <div className="rule-catalog-grid">{catalogue.data.map(rule => <article className="rule-catalog-card" key={rule.rule_id}><div className="detection-feed-top"><span className="rule-id">{rule.rule_id} · v{rule.version}</span><span className={`case-severity ${rule.severity.toLowerCase()}`}>{rule.severity}</span></div><h3>{rule.name}</h3><p>{rule.description}</p><div className="rule-threshold-list">{rule.thresholds.map(item => <span key={item.name}>{displayLabel(item.name)}: <strong>{item.value}{item.unit ? ` ${item.unit}` : ''}</strong></span>)}</div><small>History: {rule.minimum_history}</small></article>)}</div> : <ApiState loading={false} error={null} empty={<><strong>No rule definitions available</strong><span>The configured API returned an empty rule catalogue.</span></>} />}
    </section>

    <div className="ops-toolbar"><div className="ops-filters"><label>Evaluation outcome <select value={outcome} onChange={event => { setOutcome(event.target.value as Outcome); setSelectedId(null) }}><option value="">All outcomes</option><option value="TRIGGERED">Triggered</option><option value="NOT_TRIGGERED">Not triggered</option><option value="NOT_EVALUATED">Not evaluated</option></select></label></div><div className="ops-toolbar-actions"><span className="ops-muted">{evaluations.data?.total ?? 0} persisted outcomes · latest 100 shown</span><button className="text-button" type="button" onClick={() => setRefreshKey(value => value + 1)}>Refresh</button></div></div>

    <div className="intelligence-grid"><section className="panel ops-panel"><div className="panel-heading"><div><h2>Persisted evaluation outcomes</h2><p>NOT_EVALUATED is distinct from a negative rule result</p></div></div>
      {evaluations.error || (evaluations.loading && !evaluations.data) ? <ApiState loading={evaluations.loading} error={evaluations.error} retry={evaluations.retry} /> : rows.length ? <div className="evaluation-list">{rows.map(row => <button type="button" key={row.id} className={`evaluation-item ${row.outcome.toLowerCase()} ${selected?.id === row.id ? 'selected' : ''}`} onClick={() => setSelectedId(row.id)} aria-pressed={selected?.id === row.id}><span className={`outcome-pill ${row.outcome.toLowerCase()}`}>{displayLabel(row.outcome)}</span><strong>{row.rule_name}</strong><span>{row.rule_id} · {row.rule_version}</span><small>{formatOpsDate(row.detected_at)} · {formatOpsMoney(row.transaction_amount, row.currency)}</small></button>)}</div> : <ApiState loading={false} error={null} empty={<><strong>No evaluation records</strong><span>Only persisted rule evaluations are shown here. Outbox messages are excluded.</span></>} />}
    </section>

    <section className="panel ops-panel intelligence-detail"><div className="panel-heading"><div><h2>Evaluation detail</h2><p>Rule output and incident risk context</p></div></div>
      {selected ? <><div className="evaluation-summary"><span className={`outcome-pill ${selected.outcome.toLowerCase()}`}>{displayLabel(selected.outcome)}</span><h3>{selected.rule_name}</h3><code>{selected.rule_id} · {selected.rule_version}</code><p>{selected.explanation}</p><div className="inspect-fields"><div><span>Severity label</span><strong>{displayLabel(selected.severity)}</strong></div><div><span>Transaction</span><strong className="mono">{selected.transaction_id}</strong></div><div><span>Value</span><strong>{formatOpsMoney(selected.transaction_amount, selected.currency)}</strong></div><div><span>Evaluated at</span><strong>{formatOpsDate(selected.detected_at)}</strong></div></div></div>
        {selected.limitation && <div className="limitation-callout"><strong>Evaluation limitation</strong><span>{selected.limitation}</span></div>}
        <h3 className="ops-subheading">Measured evidence</h3><EvidenceList items={selected.evidence} />
        {selected.incident_id ? incident.error || (incident.loading && !incident.data) ? <ApiState loading={incident.loading} error={incident.error} retry={incident.retry} /> : incident.data && <><h3 className="ops-subheading">Persisted risk contributions</h3><p className="ops-muted">Incident {incident.data.id} · score {incident.data.risk_score}/100 · {displayLabel(incident.data.risk_band)}</p>{incident.data.risk_evidence.length ? <div className="risk-contribution-list">{incident.data.risk_evidence.map((item, index) => <article key={`${item.family}-${index}`}><strong>{displayLabel(item.family)} · +{item.weight}</strong><span>{item.rule_ids.map(id => catalogueById.get(id)?.name ?? id).join(', ')}</span><small>{item.overlapping_detection_count} overlapping rule signal(s) counted once in this family.</small></article>)}</div> : <p className="ops-muted">No persisted risk contributions.</p>}</> : <div className="ops-empty-inline">This evaluation is not linked to a correlated incident, so no incident risk contribution is available.</div>}
      </> : <div className="ops-empty-inline">Select an evaluation to inspect evidence and any associated incident score.</div>}
    </section></div>
  </div>
}
