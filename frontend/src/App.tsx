import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import './App.css'

type EventStatus = 'Blocked' | 'Review' | 'Investigating'
type RiskLevel = 'Low' | 'Guarded' | 'Elevated' | 'Critical'
type SortKey = 'time' | 'amount' | 'score'
type SortDirection = 'asc' | 'desc'
type CaseSeverity = 'Critical' | 'High' | 'Medium' | 'Low'
type CaseStatus = 'Open' | 'Investigating' | 'Escalated' | 'Resolved'
type DetectionDomain = 'Transaction fraud' | 'Account takeover' | 'AML' | 'Behavioral analytics'
type CaseSort = 'newest' | 'oldest' | 'severity-high' | 'severity-low'

type InvestigationCase = {
  id: string
  title: string
  description: string
  severity: CaseSeverity
  status: CaseStatus
  analyst: string
  createdAt: string
  updatedAt: string
  transactions: string[]
  domains: DetectionDomain[]
  evidence: string[]
  timeline: { timestamp: string; title: string; detail: string }[]
  notes: string[]
}

type AnalystNote = { text: string; createdAt: string }

type SecurityEvent = {
  id: string
  time: string
  type: string
  entity: string
  amount: string
  amountValue: number
  score: number
  status: EventStatus
  transaction: {
    senderAccount: string
    beneficiaryAccount: string
    channel: 'Card' | 'Bank transfer' | 'Simulated UPI'
    reference: string
    transactionLocation: string
  }
  evidence: string[]
  deviceContext: {
    deviceId: string
    deviceType: string
    browser: string
    ipAddress: string
    sessionId: string
  }
  timeline: { time: string; title: string; detail: string }[]
  recommendations: string[]
}

function classifyRiskScore(score: number): RiskLevel {
  if (score >= 75) return 'Critical'
  if (score >= 50) return 'Elevated'
  if (score >= 25) return 'Guarded'
  return 'Low'
}

const navigation = [
  { name: 'Command Center', icon: '⌂' },
  { name: 'Live Monitoring', icon: '◉' },
  { name: 'Intelligence', icon: '⌁' },
  { name: 'Geospatial Intelligence', icon: '◎' },
  { name: 'Investigation Center', icon: '⌕' },
  { name: 'Response & Audit', icon: '↗' },
]

const events: SecurityEvent[] = [
  { id: 'TXN-94821', time: '10:42:18', type: 'Account takeover', entity: 'Northstar Retail ·•• 4821', amount: '$18,450.00', amountValue: 18450, score: 94, status: 'Blocked', transaction: { senderAccount: 'ACCT-SYN-004821', beneficiaryAccount: 'BEN-SYN-882104', channel: 'Card', reference: 'REF-SYN-94821-A', transactionLocation: 'Merchant terminal · Singapore' }, evidence: ['Transaction amount is 4.8× the account median', 'New device fingerprint observed 6 minutes before payment', 'Login location shifted from Singapore to Frankfurt within 18 minutes'], deviceContext: { deviceId: 'DEV-SYN-71A4C2', deviceType: 'Windows laptop', browser: 'Chrome 130', ipAddress: '192.0.2.44', sessionId: 'SES-SYN-8F21D0' }, timeline: [{ time: '10:24:09', title: 'Session established', detail: 'New browser session began from a documentation-range IP.' }, { time: '10:36:42', title: 'Beneficiary selected', detail: 'Saved beneficiary had no prior successful payments.' }, { time: '10:42:18', title: 'Transaction blocked', detail: 'Synthetic risk policy decision at score 94.' }], recommendations: ['Review the account takeover signals', 'Request additional authentication before any retry', 'Escalate investigation for analyst review'] },
  { id: 'TXN-94819', time: '10:39:54', type: 'Unusual velocity', entity: 'Meridian Pay ·•• 1093', amount: '$6,280.50', amountValue: 6280.5, score: 87, status: 'Review', transaction: { senderAccount: 'ACCT-SYN-001093', beneficiaryAccount: 'BEN-SYN-407725', channel: 'Bank transfer', reference: 'REF-SYN-94819-B', transactionLocation: 'Branch-originated transfer · Toronto' }, evidence: ['7 transfer attempts in a 4-minute window', 'Aggregate attempted value is above the account velocity baseline', 'Beneficiary account was created earlier today'], deviceContext: { deviceId: 'DEV-SYN-33BC10', deviceType: 'Android phone', browser: 'Chrome Mobile 129', ipAddress: '198.51.100.27', sessionId: 'SES-SYN-0A9C43' }, timeline: [{ time: '10:35:11', title: 'First transfer attempt', detail: 'A small verification transfer was submitted.' }, { time: '10:38:47', title: 'Velocity threshold crossed', detail: 'Repeated transfer attempts raised a synthetic signal.' }, { time: '10:39:54', title: 'Queued for review', detail: 'Transaction held for analyst assessment at score 87.' }], recommendations: ['Review the recent transfer sequence', 'Maintain the temporary review hold', 'Confirm beneficiary ownership with the account holder'] },
  { id: 'TXN-94816', time: '10:36:02', type: 'Beneficiary risk', entity: 'Cobalt Financial ·•• 7702', amount: '$2,100.00', amountValue: 2100, score: 76, status: 'Investigating', transaction: { senderAccount: 'ACCT-SYN-007702', beneficiaryAccount: 'BEN-SYN-119308', channel: 'Simulated UPI', reference: 'REF-SYN-94816-C', transactionLocation: 'QR merchant payment · Bengaluru' }, evidence: ['Beneficiary is associated with several synthetic chargeback reports', 'First payment to this beneficiary', 'Amount is above the sender’s usual UPI range'], deviceContext: { deviceId: 'DEV-SYN-94DE21', deviceType: 'Android phone', browser: 'WebView 128', ipAddress: '203.0.113.62', sessionId: 'SES-SYN-64F3A2' }, timeline: [{ time: '10:12:20', title: 'Beneficiary added', detail: 'New payee details were entered in the simulated UPI flow.' }, { time: '10:35:48', title: 'Risk context matched', detail: 'Synthetic beneficiary risk indicators were attached.' }, { time: '10:36:02', title: 'Investigation opened', detail: 'Analyst review initiated at score 76.' }], recommendations: ['Review beneficiary history and linked reports', 'Request additional authentication', 'Escalate if the beneficiary relationship cannot be verified'] },
  { id: 'TXN-94810', time: '10:31:47', type: 'Device anomaly', entity: 'Atlas Commerce ·•• 3318', amount: '$940.25', amountValue: 940.25, score: 68, status: 'Review', transaction: { senderAccount: 'ACCT-SYN-003318', beneficiaryAccount: 'BEN-SYN-902611', channel: 'Card', reference: 'REF-SYN-94810-D', transactionLocation: 'E-commerce merchant · Dublin' }, evidence: ['Device identifier has not appeared on this account before', 'Browser language differs from the account’s recent sessions', 'Transaction amount remains within the account’s usual range'], deviceContext: { deviceId: 'DEV-SYN-A022F8', deviceType: 'macOS desktop', browser: 'Safari 18', ipAddress: '192.0.2.118', sessionId: 'SES-SYN-3B109E' }, timeline: [{ time: '10:29:03', title: 'Device first seen', detail: 'A new desktop fingerprint began a session.' }, { time: '10:30:51', title: 'Card authorization requested', detail: 'E-commerce authorization submitted from the new device.' }, { time: '10:31:47', title: 'Review requested', detail: 'Device signals prompted a synthetic review status.' }], recommendations: ['Review device history with the customer', 'Request step-up authentication', 'Release the review hold only after verification'] },
  { id: 'TXN-94804', time: '10:28:11', type: 'Geo-velocity', entity: 'Juniper Credit ·•• 6250', amount: '$12,760.00', amountValue: 12760, score: 91, status: 'Blocked', transaction: { senderAccount: 'ACCT-SYN-006250', beneficiaryAccount: 'BEN-SYN-381440', channel: 'Bank transfer', reference: 'REF-SYN-94804-E', transactionLocation: 'Receiving bank · Amsterdam' }, evidence: ['Unusual login location was recorded shortly before transfer', 'Account activity shifted between distant regions within 11 minutes', 'Transfer amount exceeds the normal international payment range'], deviceContext: { deviceId: 'DEV-SYN-510CE9', deviceType: 'Windows desktop', browser: 'Edge 130', ipAddress: '198.51.100.88', sessionId: 'SES-SYN-E8A417' }, timeline: [{ time: '10:17:02', title: 'Login observed', detail: 'Synthetic session began from a location not seen in recent history.' }, { time: '10:25:31', title: 'Transfer created', detail: 'International beneficiary selected for a high-value transfer.' }, { time: '10:28:11', title: 'Transaction blocked', detail: 'Location and amount signals resulted in a score of 91.' }], recommendations: ['Escalate for geo-velocity review', 'Maintain the temporary hold', 'Request confirmation through a verified contact channel'] },
  { id: 'TXN-94798', time: '10:24:36', type: 'Credential stuffing', entity: 'Harborline Bank ·•• 8104', amount: '$4,320.00', amountValue: 4320, score: 58, status: 'Investigating', transaction: { senderAccount: 'ACCT-SYN-008104', beneficiaryAccount: 'BEN-SYN-624809', channel: 'Card', reference: 'REF-SYN-94798-F', transactionLocation: 'Online merchant · Seattle' }, evidence: ['Multiple failed sign-ins preceded the payment attempt', 'Successful session followed a sequence of username probes', 'Transaction amount is moderately above the account median'], deviceContext: { deviceId: 'DEV-SYN-30F1B6', deviceType: 'Linux laptop', browser: 'Firefox 131', ipAddress: '203.0.113.143', sessionId: 'SES-SYN-4C70B1' }, timeline: [{ time: '10:18:09', title: 'Repeated sign-in failures', detail: 'Several invalid credential attempts were recorded.' }, { time: '10:22:40', title: 'Session authenticated', detail: 'A subsequent synthetic session passed primary authentication.' }, { time: '10:24:36', title: 'Investigation opened', detail: 'Credential activity linked to a card payment attempt.' }], recommendations: ['Review the authentication sequence', 'Request additional authentication', 'Escalate if credential reuse is suspected'] },
  { id: 'TXN-94793', time: '10:19:05', type: 'New device', entity: 'Pioneer Exchange ·•• 2941', amount: '$1,580.75', amountValue: 1580.75, score: 43, status: 'Review', transaction: { senderAccount: 'ACCT-SYN-002941', beneficiaryAccount: 'BEN-SYN-701163', channel: 'Simulated UPI', reference: 'REF-SYN-94793-G', transactionLocation: 'Retail checkout · Hyderabad' }, evidence: ['First transaction from a newly registered device', 'Login location matches the account’s usual region', 'Amount is within typical purchase range'], deviceContext: { deviceId: 'DEV-SYN-902A6D', deviceType: 'Android tablet', browser: 'Chrome 129', ipAddress: '192.0.2.205', sessionId: 'SES-SYN-C1230A' }, timeline: [{ time: '10:04:52', title: 'Device registered', detail: 'A new device was added after account sign-in.' }, { time: '10:18:57', title: 'Payment initiated', detail: 'Simulated UPI payment initiated at a familiar location.' }, { time: '10:19:05', title: 'Review queued', detail: 'First-use device prompted a guarded review.' }], recommendations: ['Review recent device registration', 'Request additional authentication if device ownership is unclear'] },
  { id: 'TXN-94787', time: '10:14:52', type: 'Beneficiary change', entity: 'Silveroak Payments ·•• 6732', amount: '$7,900.00', amountValue: 7900, score: 32, status: 'Investigating', transaction: { senderAccount: 'ACCT-SYN-006732', beneficiaryAccount: 'BEN-SYN-274410', channel: 'Bank transfer', reference: 'REF-SYN-94787-H', transactionLocation: 'Domestic transfer · Chicago' }, evidence: ['Beneficiary details were edited shortly before the transfer', 'Transaction amount is above the account median', 'Edit was completed from a previously recognized device'], deviceContext: { deviceId: 'DEV-SYN-05C9A3', deviceType: 'Windows laptop', browser: 'Chrome 130', ipAddress: '198.51.100.191', sessionId: 'SES-SYN-2D70F8' }, timeline: [{ time: '10:07:20', title: 'Beneficiary updated', detail: 'Account holder details were edited in the synthetic profile.' }, { time: '10:13:59', title: 'Transfer drafted', detail: 'New beneficiary selected for a higher-than-usual transfer.' }, { time: '10:14:52', title: 'Investigation opened', detail: 'Change-to-transfer sequence routed for analyst review.' }], recommendations: ['Verify the beneficiary change with the account holder', 'Maintain a temporary hold while details are checked'] },
  { id: 'TXN-94782', time: '10:08:23', type: 'Unusual login', entity: 'Cedar Federal ·•• 4486', amount: '$265.40', amountValue: 265.4, score: 21, status: 'Review', transaction: { senderAccount: 'ACCT-SYN-004486', beneficiaryAccount: 'BEN-SYN-833029', channel: 'Card', reference: 'REF-SYN-94782-J', transactionLocation: 'Grocery merchant · Portland' }, evidence: ['Login time differs from the account’s typical activity window', 'Recognized device and familiar transaction location', 'Low-value transaction is within normal spending range'], deviceContext: { deviceId: 'DEV-SYN-19B4EE', deviceType: 'iPhone', browser: 'Safari Mobile 18', ipAddress: '203.0.113.9', sessionId: 'SES-SYN-7DA320' }, timeline: [{ time: '09:58:31', title: 'Session resumed', detail: 'Existing recognized device resumed an account session.' }, { time: '10:08:16', title: 'Card payment authorized', detail: 'Low-value purchase initiated at a familiar merchant location.' }, { time: '10:08:23', title: 'Low-risk review', detail: 'Unusual timing signal recorded at score 21.' }], recommendations: ['Review the login time signal alongside account history', 'No immediate action is indicated by this synthetic low-risk score'] },
  { id: 'TXN-94776', time: '10:03:17', type: 'First-time payee', entity: 'Bluepeak Markets ·•• 5230', amount: '$112.00', amountValue: 112, score: 14, status: 'Investigating', transaction: { senderAccount: 'ACCT-SYN-005230', beneficiaryAccount: 'BEN-SYN-609515', channel: 'Simulated UPI', reference: 'REF-SYN-94776-K', transactionLocation: 'Cafe merchant QR · Pune' }, evidence: ['First payment to this payee', 'Small transaction amount consistent with account history', 'Known device and usual login region'], deviceContext: { deviceId: 'DEV-SYN-84AA01', deviceType: 'Android phone', browser: 'WebView 129', ipAddress: '192.0.2.76', sessionId: 'SES-SYN-11B9CF' }, timeline: [{ time: '09:51:08', title: 'Payee entered', detail: 'New payee details were entered into the simulated UPI flow.' }, { time: '10:03:11', title: 'Payment submitted', detail: 'Small QR payment submitted from a known device.' }, { time: '10:03:17', title: 'Signal recorded', detail: 'First-time payee signal retained for investigation context.' }], recommendations: ['Confirm the new payee was intentional if contacted by the customer', 'Keep the investigation notes for audit context'] },
  { id: 'TXN-94770', time: '09:57:41', type: 'Location mismatch', entity: 'Westbridge Credit ·•• 9912', amount: '$780.00', amountValue: 780, score: 8, status: 'Review', transaction: { senderAccount: 'ACCT-SYN-009912', beneficiaryAccount: 'BEN-SYN-500621', channel: 'Card', reference: 'REF-SYN-94770-L', transactionLocation: 'Fuel station terminal · Denver' }, evidence: ['Merchant transaction location differs from a recent device login region', 'Amount is typical for this merchant category', 'No new device or elevated velocity signals observed'], deviceContext: { deviceId: 'DEV-SYN-611C20', deviceType: 'MacBook Air', browser: 'Safari 18', ipAddress: '198.51.100.14', sessionId: 'SES-SYN-98E034' }, timeline: [{ time: '09:42:06', title: 'Account session active', detail: 'Known device session established in the synthetic account region.' }, { time: '09:57:38', title: 'Card authorization requested', detail: 'Fuel station purchase submitted from a different transaction location.' }, { time: '09:57:41', title: 'Informational signal logged', detail: 'Location mismatch retained as low-risk context at score 8.' }], recommendations: ['Compare transaction location with expected travel context', 'Use analyst judgment; this synthetic signal alone is low risk'] },
]

const cases: InvestigationCase[] = [
  { id: 'CASE-2026-0418', title: 'Coordinated account takeover activity', description: 'Several synthetic accounts show a shared pattern of new-device access followed by high-value transfers to recently added beneficiaries.', severity: 'Critical', status: 'Investigating', analyst: 'Alex Morgan', createdAt: '2026-11-07T09:42:00Z', updatedAt: '2026-11-07T10:42:00Z', transactions: ['TXN-94821', 'TXN-94804'], domains: ['Account takeover', 'Transaction fraud', 'Behavioral analytics'], evidence: ['Two accounts accessed from new device fingerprints within a short interval', 'High-value transactions followed beneficiary changes', 'Synthetic device overlap links the activity pattern'], timeline: [{ timestamp: '2026-11-07T09:42:00Z', title: 'Case opened', detail: 'Correlated account access and transaction signals grouped for review.' }, { timestamp: '2026-11-07T10:05:00Z', title: 'Related transactions linked', detail: 'Two sample transaction records associated with the pattern.' }, { timestamp: '2026-11-07T10:42:00Z', title: 'Analyst review started', detail: 'Alex Morgan began evidence review.' }], notes: ['Compare beneficiary change timing across the linked sample records.'] },
  { id: 'CASE-2026-0417', title: 'Rapid transfer attempts to new beneficiary', description: 'A burst of transfer activity exceeded the synthetic account velocity baseline after a beneficiary was added.', severity: 'High', status: 'Open', analyst: 'Priya Shah', createdAt: '2026-11-07T09:18:00Z', updatedAt: '2026-11-07T10:39:00Z', transactions: ['TXN-94819', 'TXN-94787'], domains: ['Transaction fraud', 'Behavioral analytics'], evidence: ['Seven transfer attempts recorded in four minutes', 'Beneficiary was created on the same day', 'Aggregate attempted amount exceeds the usual account range'], timeline: [{ timestamp: '2026-11-07T09:18:00Z', title: 'Case opened', detail: 'Transfer velocity signal crossed the synthetic review threshold.' }, { timestamp: '2026-11-07T10:39:00Z', title: 'Case refreshed', detail: 'A related beneficiary update sample was attached.' }], notes: [] },
  { id: 'CASE-2026-0416', title: 'Beneficiary linked to reported chargebacks', description: 'A new payee has synthetic risk references and was used in a first-time payment from a retail account.', severity: 'High', status: 'Escalated', analyst: 'Jordan Lee', createdAt: '2026-11-07T08:55:00Z', updatedAt: '2026-11-07T10:36:00Z', transactions: ['TXN-94816'], domains: ['Transaction fraud', 'AML'], evidence: ['Beneficiary has multiple synthetic chargeback references', 'First payment to payee', 'Payment amount is above the sender’s usual simulated UPI range'], timeline: [{ timestamp: '2026-11-07T08:55:00Z', title: 'Case opened', detail: 'Beneficiary context matched a synthetic risk indicator.' }, { timestamp: '2026-11-07T10:36:00Z', title: 'Escalated for review', detail: 'Case escalated for a second analyst perspective.' }], notes: ['Check the synthetic beneficiary references before closing.'] },
  { id: 'CASE-2026-0415', title: 'Credential probing followed by payment attempt', description: 'Repeated failed sign-ins preceded an authenticated session and a card payment attempt.', severity: 'Medium', status: 'Investigating', analyst: 'Alex Morgan', createdAt: '2026-11-07T08:34:00Z', updatedAt: '2026-11-07T10:24:00Z', transactions: ['TXN-94798'], domains: ['Account takeover', 'Behavioral analytics', 'Transaction fraud'], evidence: ['Multiple invalid sign-in attempts', 'Successful session shortly after credential probes', 'Payment amount moderately exceeds the account median'], timeline: [{ timestamp: '2026-11-07T08:34:00Z', title: 'Case opened', detail: 'Authentication anomaly linked to a payment event.' }, { timestamp: '2026-11-07T09:12:00Z', title: 'Session context reviewed', detail: 'Synthetic session context added to the case.' }, { timestamp: '2026-11-07T10:24:00Z', title: 'Payment attached', detail: 'Card transaction sample linked to the investigation.' }], notes: [] },
  { id: 'CASE-2026-0414', title: 'New device used for a simulated UPI payment', description: 'A newly registered device initiated a payment from a familiar region; the amount is within expected range.', severity: 'Medium', status: 'Open', analyst: 'Mina Patel', createdAt: '2026-11-07T08:12:00Z', updatedAt: '2026-11-07T10:19:00Z', transactions: ['TXN-94793'], domains: ['Account takeover', 'Behavioral analytics'], evidence: ['Device fingerprint is new to the account', 'Login and transaction locations are regionally consistent', 'Payment amount matches the account purchase profile'], timeline: [{ timestamp: '2026-11-07T08:12:00Z', title: 'Case opened', detail: 'New device signal queued for analyst assessment.' }, { timestamp: '2026-11-07T10:19:00Z', title: 'Payment linked', detail: 'Simulated UPI purchase record attached.' }], notes: [] },
  { id: 'CASE-2026-0413', title: 'Beneficiary edits before domestic transfer', description: 'Beneficiary details changed shortly before a higher-than-usual domestic transfer from a recognized device.', severity: 'Low', status: 'Resolved', analyst: 'Priya Shah', createdAt: '2026-11-06T16:30:00Z', updatedAt: '2026-11-07T09:52:00Z', transactions: ['TXN-94787'], domains: ['Transaction fraud', 'Behavioral analytics'], evidence: ['Beneficiary edit preceded the transfer by under ten minutes', 'Recognized device used throughout the session', 'Transfer recipient was confirmed in synthetic case notes'], timeline: [{ timestamp: '2026-11-06T16:30:00Z', title: 'Case opened', detail: 'Beneficiary edit sequence flagged for review.' }, { timestamp: '2026-11-07T09:52:00Z', title: 'Case resolved', detail: 'Sample scenario marked resolved after confirmation.' }], notes: ['Synthetic confirmation recorded; no customer contact was made.'] },
  { id: 'CASE-2026-0412', title: 'Unusual login hour with familiar device', description: 'A session outside the account’s typical activity window preceded a low-value purchase from a known device.', severity: 'Low', status: 'Resolved', analyst: 'Jordan Lee', createdAt: '2026-11-06T14:05:00Z', updatedAt: '2026-11-06T15:20:00Z', transactions: ['TXN-94782'], domains: ['Behavioral analytics'], evidence: ['Session time differs from the usual activity window', 'Known device and familiar transaction region', 'Transaction amount is consistent with account history'], timeline: [{ timestamp: '2026-11-06T14:05:00Z', title: 'Case opened', detail: 'Login timing signal recorded for review.' }, { timestamp: '2026-11-06T15:20:00Z', title: 'Case resolved', detail: 'Low-risk sample scenario closed with no further indicators.' }], notes: [] },
  { id: 'CASE-2026-0411', title: 'International transfer with location mismatch', description: 'A high-value transfer followed an account session from a region not present in recent sample history.', severity: 'Critical', status: 'Escalated', analyst: 'Mina Patel', createdAt: '2026-11-06T12:48:00Z', updatedAt: '2026-11-07T08:10:00Z', transactions: ['TXN-94804', 'TXN-94821'], domains: ['Transaction fraud', 'Account takeover', 'AML'], evidence: ['Large transfer to an international receiving bank', 'Session location shifted between distant regions in a short interval', 'Related account signals overlap with another open synthetic case'], timeline: [{ timestamp: '2026-11-06T12:48:00Z', title: 'Case opened', detail: 'Geo-velocity and high-value transfer indicators grouped.' }, { timestamp: '2026-11-06T13:20:00Z', title: 'Related activity identified', detail: 'Overlapping synthetic indicators linked for context.' }, { timestamp: '2026-11-07T08:10:00Z', title: 'Escalated', detail: 'Case elevated for senior analyst review.' }], notes: ['Maintain the demo hold status in the scenario record; no live action is connected.'] },
]

const distribution = [
  { label: 'Low', count: '9,241', percent: 72, color: 'low' },
  { label: 'Guarded', count: '2,614', percent: 20, color: 'guarded' },
  { label: 'Elevated', count: '874', percent: 7, color: 'elevated' },
  { label: 'Critical', count: '127', percent: 1, color: 'critical' },
]

function Icon({ children }: { children: string }) {
  return <span className="nav-icon" aria-hidden="true">{children}</span>
}

function Sidebar({ active, onSelect }: { active: string; onSelect: (name: string) => void }) {
  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark"><span>F</span><i /></div><div><strong>FINGUARD <b>X</b></strong><small>FINANCIAL INTELLIGENCE</small></div></div>
    <div className="workspace-label">OPERATIONS</div>
    <nav>{navigation.map((item, i) => <button key={item.name} className={`nav-item ${active === item.name ? 'active' : ''}`} onClick={() => onSelect(item.name)}><Icon>{item.icon}</Icon><span>{item.name}</span>{i === 1 && <span className="nav-live" />}</button>)}</nav>
    <div className="sidebar-bottom"><div className="analyst-avatar">AM</div><div className="analyst-info"><strong>Alex Morgan</strong><span>Security Analyst</span></div><button className="more-button" aria-label="Profile options">···</button></div>
  </aside>
}

function MetricCard({ label, value, delta, note, icon, tone }: { label: string; value: string; delta: string; note: string; icon: string; tone: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}>{icon}</span></div><div className="metric-value">{value}</div><div className="metric-foot"><span className="metric-delta">{delta}</span><span>{note}</span></div></article>
}

function RiskDistribution() {
  return <section className="panel risk-panel"><div className="panel-heading"><div><h2>Risk distribution</h2><p>Synthetic aggregate · all 12,856 transactions · last 24 hours</p></div><button className="quiet-select">24 hours <span>⌄</span></button></div>
    <div className="risk-content"><div className="donut-wrap"><div className="donut"><div className="donut-hole"><strong>12,856</strong><span>TRANSACTIONS</span></div></div></div><div className="risk-legend">{distribution.map(item => <div className="risk-row" key={item.label}><span className={`legend-dot ${item.color}`} /><span className="risk-label">{item.label}</span><strong>{item.count}</strong><span className="risk-percent">{item.percent}%</span></div>)}</div></div>
    <div className="risk-note"><span className="status-dot" /> Risk scores recalculated continuously</div>
  </section>
}

const statusOptions: EventStatus[] = ['Blocked', 'Review', 'Investigating']
const riskOptions: RiskLevel[] = ['Low', 'Guarded', 'Elevated', 'Critical']

function sortEvents(rows: SecurityEvent[], sortKey: SortKey, direction: SortDirection) {
  const multiplier = direction === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const difference = sortKey === 'time'
      ? a.time.localeCompare(b.time)
      : sortKey === 'amount'
        ? a.amountValue - b.amountValue
        : a.score - b.score
    return difference * multiplier
  })
}

function filterEvents(rows: SecurityEvent[], status: EventStatus | '', risk: RiskLevel | '') {
  return rows.filter(event => (!status || event.status === status) && (!risk || classifyRiskScore(event.score) === risk))
}

function DetailField({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="detail-field"><span>{label}</span><strong className={mono ? 'mono' : ''}>{value}</strong></div>
}

function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="drawer-section"><h3>{title}</h3>{children}</section>
}

function EventDetailDrawer({ event, onClose }: { event: SecurityEvent; onClose: () => void }) {
  const riskLevel = classifyRiskScore(event.score)
  return <>
    <button className="drawer-backdrop" aria-label="Close investigation details" onClick={onClose} />
    <aside className="investigation-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <header className="drawer-header"><div><span className="drawer-kicker">INVESTIGATION VIEW <i>·</i> <b>DEMO DATA</b></span><h2 id="drawer-title">{event.id}</h2><p>{event.type}</p></div><button className="drawer-close" autoFocus onClick={onClose} aria-label="Close event details">×</button></header>
      <div className="drawer-scroll">
        <div className="drawer-synthetic-note"><span className="demo-icon">i</span><span>Synthetic event record. Details are illustrative and do not reflect a live transaction.</span></div>
        <DrawerSection title="Event overview"><div className="detail-grid"><DetailField label="Event ID" value={event.id} mono /><DetailField label="Detection type" value={event.type} /><DetailField label="Transaction amount" value={event.amount} mono /><DetailField label="Timestamp" value={`2026-11-07 ${event.time} UTC`} mono /><DetailField label="Current status" value={event.status} /><DetailField label="Risk score" value={`${event.score} / 100 · ${riskLevel}`} /></div></DrawerSection>
        <DrawerSection title="Transaction details"><div className="detail-grid"><DetailField label="Sender account" value={event.transaction.senderAccount} mono /><DetailField label="Beneficiary account" value={event.transaction.beneficiaryAccount} mono /><DetailField label="Transaction channel" value={event.transaction.channel} /><DetailField label="Transaction reference" value={event.transaction.reference} mono /><div className="location-callout"><span>TRANSACTION LOCATION</span><strong>{event.transaction.transactionLocation}</strong><small>Merchant or transfer destination location. Physical login/device location is separate context.</small></div></div></DrawerSection>
        <DrawerSection title="Risk evidence"><ul className="evidence-list">{event.evidence.map(signal => <li key={signal}><span className="evidence-mark">!</span>{signal}</li>)}</ul></DrawerSection>
        <DrawerSection title="Device & session context"><div className="detail-grid"><DetailField label="Device identifier" value={event.deviceContext.deviceId} mono /><DetailField label="Device type" value={event.deviceContext.deviceType} /><DetailField label="Browser" value={event.deviceContext.browser} /><DetailField label="Example IP address" value={event.deviceContext.ipAddress} mono /><DetailField label="Session identifier" value={event.deviceContext.sessionId} mono /></div><p className="ip-note">IP uses an RFC 5737 documentation range and is reserved for examples.</p></DrawerSection>
        <DrawerSection title="Event timeline"><ol className="event-timeline">{event.timeline.map((item, index) => <li key={`${item.time}-${item.title}`} className={index === event.timeline.length - 1 ? 'current' : ''}><span className="timeline-time">{item.time} UTC</span><strong>{item.title}</strong><p>{item.detail}</p></li>)}</ol></DrawerSection>
        <DrawerSection title="Recommended analyst actions"><p className="recommendation-note">Suggestions only · no account or transaction actions are performed.</p><ul className="recommendation-list">{event.recommendations.map(action => <li key={action}><span>↗</span>{action}</li>)}</ul></DrawerSection>
      </div>
    </aside>
  </>
}

function EventsTable({ selectedEventId, onSelectEvent }: { selectedEventId: string | null; onSelectEvent: (event: SecurityEvent) => void }) {
  const [statusFilter, setStatusFilter] = useState<EventStatus | ''>('')
  const [riskFilter, setRiskFilter] = useState<RiskLevel | ''>('')
  const [sortKey, setSortKey] = useState<SortKey>('time')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const hasActiveFilters = Boolean(statusFilter || riskFilter)
  const visibleEvents = useMemo(() => sortEvents(filterEvents(events, statusFilter, riskFilter), sortKey, sortDirection), [statusFilter, riskFilter, sortKey, sortDirection])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDirection(direction => direction === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDirection(key === 'time' ? 'desc' : 'asc') }
  }
  const sortLabel = (key: SortKey, label: string) => <button className="table-sort" onClick={() => toggleSort(key)} aria-label={`Sort by ${label}${sortKey === key ? `, currently ${sortDirection === 'asc' ? 'ascending' : 'descending'}` : ''}`} aria-pressed={sortKey === key}>{label}{sortKey === key && <span aria-hidden="true">{sortDirection === 'asc' ? ' ↑' : ' ↓'}</span>}</button>

  return <section className="panel events-panel"><div className="panel-heading"><div><h2>Recent security events</h2><p>Sample synthetic events · not a complete view of aggregate transactions</p></div><button className="text-button">View all events <span>↗</span></button></div>
    <div className="table-controls"><label>Status <select aria-label="Filter events by status" value={statusFilter} onChange={event => setStatusFilter(event.target.value as EventStatus | '')}><option value="">All statuses</option>{statusOptions.map(status => <option key={status} value={status}>{status}</option>)}</select></label><label>Risk level <select aria-label="Filter events by risk level" value={riskFilter} onChange={event => setRiskFilter(event.target.value as RiskLevel | '')}><option value="">All risk levels</option>{riskOptions.map(risk => <option key={risk} value={risk}>{risk}</option>)}</select></label>{hasActiveFilters && <><span className="active-filter-indicator" role="status">Filters active · {visibleEvents.length} of {events.length} events</span><button className="clear-filters" onClick={() => { setStatusFilter(''); setRiskFilter('') }}>Clear all filters</button></>}</div>
    <div className="table-scroll"><table><thead><tr><th>{sortLabel('time', 'EVENT ID / TIME')}</th><th>DETECTION</th><th>ENTITY</th><th>{sortLabel('amount', 'AMOUNT')}</th><th>{sortLabel('score', 'RISK SCORE')}</th><th>STATUS</th></tr></thead><tbody>{visibleEvents.map(event => { const riskLevel = classifyRiskScore(event.score); return <tr key={event.id} className={`event-row ${selectedEventId === event.id ? 'selected' : ''}`} onClick={() => onSelectEvent(event)} onKeyDown={keyboardEvent => { if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') { keyboardEvent.preventDefault(); onSelectEvent(event) } }} tabIndex={0} aria-label={`Open investigation for ${event.id}, ${event.type}, risk ${riskLevel}, status ${event.status}`} aria-selected={selectedEventId === event.id}><td><strong className="event-id">{event.id}</strong><span className="cell-sub">{event.time} UTC</span></td><td><span className="event-type"><span className="event-alert">!</span>{event.type}</span></td><td>{event.entity}</td><td className="amount">{event.amount}</td><td><div className="score"><div className="score-track"><i style={{ width: `${event.score}%` }} /></div><strong>{event.score}</strong><span className={`risk-level ${riskLevel.toLowerCase()}`}>{riskLevel}</span></div></td><td><span className={`badge ${event.status.toLowerCase()}`}>{event.status}</span></td></tr> })}</tbody></table>{visibleEvents.length === 0 && <div className="empty-events" role="status"><strong>No matching synthetic events</strong><span>Try adjusting the status or risk level filters to see more sample activity.</span></div>}</div>
    <div className="table-footer"><span>Showing {visibleEvents.length} synthetic events</span><button className="text-button">Open investigation queue <span>→</span></button></div>
  </section>
}

const severityOptions: CaseSeverity[] = ['Critical', 'High', 'Medium', 'Low']
const caseStatusOptions: CaseStatus[] = ['Open', 'Investigating', 'Escalated', 'Resolved']
const severityOrder: Record<CaseSeverity, number> = { Critical: 4, High: 3, Medium: 2, Low: 1 }

function filterCases(rows: InvestigationCase[], query: string, severity: CaseSeverity | '', status: CaseStatus | '') {
  const normalizedQuery = query.trim().toLowerCase()
  return rows.filter(item => (!normalizedQuery || item.id.toLowerCase().includes(normalizedQuery) || item.title.toLowerCase().includes(normalizedQuery)) && (!severity || item.severity === severity) && (!status || item.status === status))
}

function sortCases(rows: InvestigationCase[], sort: CaseSort) {
  return [...rows].sort((a, b) => {
    if (sort === 'newest') return b.createdAt.localeCompare(a.createdAt)
    if (sort === 'oldest') return a.createdAt.localeCompare(b.createdAt)
    const severityDifference = severityOrder[b.severity] - severityOrder[a.severity]
    return sort === 'severity-high' ? severityDifference || b.createdAt.localeCompare(a.createdAt) : -severityDifference || a.createdAt.localeCompare(b.createdAt)
  })
}

function formatCaseDate(timestamp: string) {
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(timestamp)) + ' UTC'
}

function CaseMetric({ label, value, caption, tone }: { label: string; value: number; caption: string; tone: string }) {
  return <article className="case-metric"><div className="case-metric-label"><span className={`case-metric-mark ${tone}`} />{label}</div><strong>{value}</strong><span>{caption}</span></article>
}

function CaseDetails({ item, notes, onAddNote }: { item: InvestigationCase; notes: AnalystNote[]; onAddNote: (text: string) => void }) {
  const [noteDraft, setNoteDraft] = useState('')
  const submitNote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const note = noteDraft.trim()
    if (!note) return
    onAddNote(note)
    setNoteDraft('')
  }
  return <section className="case-detail-panel">
    <div className="case-detail-top"><div><span className="case-kicker">SELECTED CASE · SYNTHETIC RECORD</span><h2>{item.title}</h2><span className="case-id">{item.id}</span></div><span className={`case-severity ${item.severity.toLowerCase()}`}>{item.severity}</span></div>
    <p className="case-description">{item.description}</p>
    <div className="case-status-line"><span className={`case-status ${item.status.toLowerCase()}`}>{item.status}</span><span>Assigned to <strong>{item.analyst}</strong></span></div>
    <div className="case-detail-section"><h3>Case overview</h3><div className="case-overview-grid"><div><span>Created</span><strong>{formatCaseDate(item.createdAt)}</strong></div><div><span>Last updated</span><strong>{formatCaseDate(item.updatedAt)}</strong></div></div></div>
    <div className="case-detail-section"><h3>Related transactions</h3><div className="case-chip-list">{item.transactions.map(transaction => <span key={transaction}>{transaction}</span>)}</div></div>
    <div className="case-detail-section"><h3>Detection domains</h3><div className="case-chip-list domains">{item.domains.map(domain => <span key={domain}>{domain}</span>)}</div></div>
    <div className="case-detail-section"><h3>Synthetic evidence summary</h3><ul className="case-evidence">{item.evidence.map(signal => <li key={signal}><span>•</span>{signal}</li>)}</ul></div>
    <div className="case-detail-section"><h3>Investigation timeline</h3><ol className="case-timeline">{item.timeline.map((entry, index) => <li key={`${entry.timestamp}-${entry.title}`}><span className="case-timeline-dot" /><time>{formatCaseDate(entry.timestamp)}</time><strong>{entry.title}</strong><p>{entry.detail}</p>{index < item.timeline.length - 1 && <i className="case-timeline-line" />}</li>)}</ol></div>
    <div className="case-detail-section notes-section"><div className="notes-heading"><h3>Analyst notes</h3><span>SESSION ONLY</span></div>{item.notes.length + notes.length > 0 ? <ul className="analyst-notes">{item.notes.map((note, index) => <li key={`seed-${index}`}><p>{note}</p><small>Existing synthetic note</small></li>)}{notes.map((note, index) => <li key={`${item.id}-note-${index}`}><p>{note.text}</p><small>Added this session · {new Date(note.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></li>)}</ul> : <p className="no-notes">No notes recorded for this case yet.</p>}<form className="note-form" onSubmit={submitNote}><label htmlFor="case-note">Add a note</label><textarea id="case-note" value={noteDraft} onChange={event => setNoteDraft(event.target.value)} placeholder="Record an observation for this session..." rows={3} /><button type="submit" disabled={!noteDraft.trim()}>Add note</button><small>Notes stay in React state and are cleared when this page session ends.</small></form></div>
  </section>
}

function InvestigationCenter() {
  const [query, setQuery] = useState('')
  const [severity, setSeverity] = useState<CaseSeverity | ''>('')
  const [status, setStatus] = useState<CaseStatus | ''>('')
  const [sort, setSort] = useState<CaseSort>('newest')
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [notesByCase, setNotesByCase] = useState<Record<string, AnalystNote[]>>({})
  const filteredCases = useMemo(() => sortCases(filterCases(cases, query, severity, status), sort), [query, severity, status, sort])
  const selectedCase = filteredCases.find(item => item.id === selectedCaseId) ?? null
  const hasFilters = Boolean(query.trim() || severity || status)
  const activeCases = cases.filter(item => item.status !== 'Resolved').length
  const criticalCases = cases.filter(item => item.severity === 'Critical' && item.status !== 'Resolved').length
  const awaitingReview = cases.filter(item => item.status === 'Open').length
  const resolvedCases = cases.filter(item => item.status === 'Resolved').length
  const clearFilters = () => { setQuery(''); setSeverity(''); setStatus('') }
  const addNote = (caseId: string, text: string) => setNotesByCase(current => ({ ...current, [caseId]: [...(current[caseId] ?? []), { text, createdAt: new Date().toISOString() }] }))

  return <div className="case-workspace">
    <div className="case-demo-strip"><span className="demo-icon">i</span><span><strong>Synthetic case-management demo</strong> All case records, evidence and activity below are illustrative sample data.</span><span className="demo-tag">DEMO DATA</span></div>
    <section className="case-metrics"><CaseMetric label="Open cases" value={activeCases} caption="unresolved cases" tone="teal" /><CaseMetric label="Critical cases" value={criticalCases} caption="active critical severity" tone="red" /><CaseMetric label="Awaiting review" value={awaitingReview} caption="newly opened cases" tone="amber" /><CaseMetric label="Resolved cases" value={resolvedCases} caption="marked resolved" tone="blue" /></section>
    <div className="case-work-area"><section className="case-queue panel"><div className="case-queue-heading"><div><h2>Case queue</h2><p>{filteredCases.length} of {cases.length} synthetic cases</p></div><span className="demo-tag">SYNTHETIC</span></div>
      <div className="case-filters"><label className="case-search"><span aria-hidden="true">⌕</span><input aria-label="Search cases by ID or title" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search case ID or title..." /></label><div className="case-filter-row"><label><span className="sr-only">Filter by severity</span><select aria-label="Filter cases by severity" value={severity} onChange={event => setSeverity(event.target.value as CaseSeverity | '')}><option value="">All severities</option>{severityOptions.map(value => <option key={value} value={value}>{value}</option>)}</select></label><label><span className="sr-only">Filter by status</span><select aria-label="Filter cases by status" value={status} onChange={event => setStatus(event.target.value as CaseStatus | '')}><option value="">All statuses</option>{caseStatusOptions.map(value => <option key={value} value={value}>{value}</option>)}</select></label><label><span className="sr-only">Sort cases</span><select aria-label="Sort cases" value={sort} onChange={event => setSort(event.target.value as CaseSort)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="severity-high">Severity: high to low</option><option value="severity-low">Severity: low to high</option></select></label></div>
      {hasFilters && <div className="case-filter-status" role="status"><span>Filters active · {filteredCases.length} matches</span><button onClick={clearFilters}>Clear all filters</button></div>}</div>
      <div className="case-list">{filteredCases.length ? filteredCases.map(item => <button type="button" key={item.id} className={`case-list-item ${selectedCaseId === item.id ? 'selected' : ''}`} onClick={() => setSelectedCaseId(item.id)} aria-pressed={selectedCaseId === item.id}><div className="case-list-top"><span className="case-id">{item.id}</span><span className={`case-severity ${item.severity.toLowerCase()}`}>{item.severity}</span></div><strong>{item.title}</strong><div className="case-list-bottom"><span className={`case-status ${item.status.toLowerCase()}`}>{item.status}</span><span>{item.analyst}</span><time>{formatCaseDate(item.createdAt)}</time></div></button>) : <div className="case-empty"><span>⌕</span><strong>No matching synthetic cases</strong><p>Try another case ID or title, or adjust the severity and status filters.</p><button onClick={clearFilters}>Clear all filters</button></div>}</div>
    </section>
    {selectedCase ? <CaseDetails key={selectedCase.id} item={selectedCase} notes={notesByCase[selectedCase.id] ?? []} onAddNote={text => addNote(selectedCase.id, text)} /> : <section className="case-detail-empty panel"><span className="case-empty-mark">⌕</span><h2>Select a case to investigate</h2><p>Choose a synthetic case from the queue to review its evidence, timeline and analyst notes.</p><span className="demo-tag">SESSION DATA</span></section>}
    </div>
  </div>
}

function App() {
  const [active, setActive] = useState('Command Center')
  const [selectedEvent, setSelectedEvent] = useState<SecurityEvent | null>(null)
  useEffect(() => {
    if (!selectedEvent) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedEvent(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedEvent])
  const isCommand = active === 'Command Center'
  const isInvestigationCenter = active === 'Investigation Center'
  return <div className="app-shell"><Sidebar active={active} onSelect={name => { setActive(name); setSelectedEvent(null) }} /><main className="main-area"><header className="topbar"><div className="breadcrumbs"><span>Workspace</span><i>/</i><strong>{active}</strong></div><div className="header-actions"><label className="search"><span>⌕</span><input placeholder="Search events, entities, or IDs..." /><kbd>⌘ K</kbd></label><button className="notification" aria-label="Notifications"><span>♧</span><i /></button><div className="system-status"><span className="status-dot" />All systems operational</div></div></header>
    <div className="content"><div className="page-heading"><div><div className="eyebrow">SECURITY OPERATIONS <span>•</span> {isInvestigationCenter ? 'CASE MANAGEMENT' : 'LIVE OVERVIEW'}</div><h1>{active}</h1><p>{isCommand ? 'Monitor financial activity and respond to emerging threats.' : isInvestigationCenter ? 'Review synthetic cases, track investigation activity and record analyst notes.' : `Explore ${active.toLowerCase()} activity and operational workflows.`}</p></div><div className="heading-right"><div className="updated"><span className="status-dot" />{isInvestigationCenter ? 'DEMO' : 'LIVE'} <i>·</i> Updated just now</div><button className="date-button">◷ <span>Last 24 hours</span><b>⌄</b></button></div></div>
    {isCommand ? <><div className="demo-banner"><span className="demo-icon">i</span><span><strong>Demo environment</strong> All metrics and events shown are synthetic sample data. No live detection engine is connected.</span><span className="demo-tag">SYNTHETIC DATA</span></div>
      <section className="metrics-grid"><MetricCard label="Transactions monitored" value="12,856" delta="↑ 8.2%" note="vs. previous 24h" icon="↗" tone="teal" /><MetricCard label="High-risk transactions" value="127" delta="↓ 12.4%" note="vs. previous 24h" icon="△" tone="amber" /><MetricCard label="Active incidents" value="18" delta="4 priority" note="requiring attention" icon="◈" tone="red" /><MetricCard label="Blocked transactions" value="342" delta="$2.84M" note="prevented exposure" icon="⊘" tone="blue" /></section>
      <div className="dashboard-grid"><RiskDistribution /><section className="panel signal-panel"><div className="panel-heading"><div><h2>Threat activity</h2><p>Flagged transactions · today</p></div><button className="quiet-select">Today <span>⌄</span></button></div><div className="signal-summary"><div><strong>1,284</strong><span>Flagged events</span></div><span className="trend-chip">↑ 6.4%</span></div><div className="chart"><div className="chart-y"><span>300</span><span>200</span><span>100</span><span>0</span></div><svg viewBox="0 0 560 150" preserveAspectRatio="none" role="img" aria-label="Synthetic threat activity by hour"><defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#35c7bd" stopOpacity=".2"/><stop offset="100%" stopColor="#35c7bd" stopOpacity="0"/></linearGradient></defs><path className="chart-fill" d="M0 120 L25 105 L50 113 L75 85 L100 92 L125 69 L150 79 L175 50 L200 66 L225 61 L250 78 L275 45 L300 55 L325 29 L350 45 L375 22 L400 37 L425 18 L450 36 L475 12 L500 27 L525 5 L560 17 L560 150 L0 150 Z"/><path className="chart-line" d="M0 120 L25 105 L50 113 L75 85 L100 92 L125 69 L150 79 L175 50 L200 66 L225 61 L250 78 L275 45 L300 55 L325 29 L350 45 L375 22 L400 37 L425 18 L450 36 L475 12 L500 27 L525 5 L560 17"/></svg><div className="chart-x"><span>00:00</span><span>04:00</span><span>08:00</span><span>12:00</span><span>16:00</span><span>20:00</span><span>24:00</span></div></div><div className="chart-foot"><span><i className="chart-key" /> Flagged transactions</span><span>Hourly volume <b>·</b> Demo data</span></div></section></div>
      <EventsTable selectedEventId={selectedEvent?.id ?? null} onSelectEvent={setSelectedEvent} /></> : isInvestigationCenter ? <InvestigationCenter /> : <section className="panel placeholder"><span className="placeholder-icon">⌁</span><h2>{active}</h2><p>This workspace is ready for the next phase of FinGuard X development.</p><span className="demo-tag">DEMO WORKSPACE</span></section>}
    {selectedEvent && <EventDetailDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />}
    <footer className="app-footer"><span>FINGUARD X <i>·</i> COMMAND CENTER</span><span>Demo environment <i>·</i> v0.1.0</span></footer></div></main></div>
}

export default App
