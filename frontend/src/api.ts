export type RiskBand = 'LOW' | 'GUARDED' | 'ELEVATED' | 'CRITICAL'
export type IncidentStatus = 'OPEN' | 'INVESTIGATING' | 'RESOLVED' | 'DISMISSED'

export type DetectionEvidence = { name: string; value: string | number | boolean; unit: string | null }

export type Detection = {
  id: string
  rule_id: string
  rule_version: string
  rule_name: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  explanation: string
  evidence: DetectionEvidence[]
  detected_at: string
  incident_id: string | null
}

export type RecentTransaction = {
  id: string
  transaction_type: 'FUNDING' | 'TRANSFER'
  sender_account: string | null
  receiver_account: string
  amount: string
  currency: string
  status: 'PENDING' | 'COMPLETED' | 'FAILED'
  created_at: string
  risk_score: number | null
  risk_band: RiskBand | null
  triggered_detection_count: number
  detections: Detection[]
}

export type RecentDetection = Detection & {
  transaction_amount: string
  currency: string
  incident_risk_score: number | null
  incident_risk_band: RiskBand | null
}

export type DashboardSummary = {
  period_start: string
  transactions_monitored: number
  high_risk_transactions: number
  active_incidents: number
  open_cases: number
  critical_cases: number
  awaiting_review: number
  resolved_cases: number
  blocked_transactions: number | null
  blocked_transactions_note: string
  triggered_detections: number
  risk_distribution: { band: RiskBand; count: number }[]
  risk_distribution_total: number
}

export type IncidentListItem = {
  id: string
  title: string
  status: IncidentStatus
  risk_score: number
  risk_band: RiskBand
  risk_explanation: string
  primary_account: string
  opened_at: string
  last_activity_at: string
  closed_at: string | null
  transaction_count: number
  detection_count: number
}

export type IncidentList = { items: IncidentListItem[]; total: number; limit: number; offset: number }

export type IncidentDetail = IncidentListItem & {
  anchor_transaction_id: string
  risk_policy_version: string
  risk_evidence: {
    family: string
    weight: number
    rule_ids: string[]
    detection_ids: string[]
    overlapping_detection_count: number
    evidence: { detection_id: string; rule_id: string; values: DetectionEvidence[] }[]
  }[]
  transactions: {
    id: string
    transaction_type: 'FUNDING' | 'TRANSFER'
    amount: string
    currency: string
    status: 'PENDING' | 'COMPLETED' | 'FAILED'
    created_at: string
  }[]
  detections: (Detection & {
    rule_description: string
    transaction_id: string
    outcome: 'TRIGGERED' | 'NOT_TRIGGERED' | 'NOT_EVALUATED'
    limitation: string | null
  })[]
  timeline: {
    id: string
    from_status: IncidentStatus | null
    to_status: IncidentStatus
    actor_identifier: string | null
    note: string | null
    changed_at: string
  }[]
}

export type RuleThreshold = { name: string; value: string | number; unit: string | null }
export type RuleCatalogItem = {
  rule_id: string
  version: string
  name: string
  description: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  required_features: string[]
  minimum_history: string
  thresholds: RuleThreshold[]
}

export type RuleEvaluation = {
  id: string
  rule_id: string
  rule_version: string
  rule_name: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  outcome: 'TRIGGERED' | 'NOT_TRIGGERED' | 'NOT_EVALUATED'
  explanation: string
  evidence: DetectionEvidence[]
  limitation: string | null
  transaction_id: string
  transaction_type: 'FUNDING' | 'TRANSFER'
  transaction_amount: string
  currency: string
  detected_at: string
  incident_id: string | null
  incident_risk_score: number | null
  incident_risk_band: RiskBand | null
}

export type RuleEvaluationPage = { items: RuleEvaluation[]; total: number; limit: number; offset: number }

export type OutboxHealth = {
  pending_count: number
  processing_count: number
  processed_count: number
  failed_count: number
  oldest_pending_at: string | null
  oldest_failed_at: string | null
  last_processed_at: string | null
  status: 'HEALTHY' | 'ATTENTION'
  note: string
}

export type GeoEventType = 'LOGIN_LOCATION' | 'TRANSACTION_ORIGIN' | 'BENEFICIARY_LOCATION' | 'TRANSACTION_ROUTE'
export type GeoCoordinate = { latitude: string | number; longitude: string | number }
export type GeoEvent = {
  id: string
  event_type: GeoEventType
  account_id: string | null
  transaction_id: string | null
  incident_id: string | null
  coordinate: GeoCoordinate | null
  event_at: string
  metadata: { synthetic: boolean; city: string | null; scenario: string | null; label: string | null }
  incident_risk_band: RiskBand | null
  incident_risk_score: number | null
}
export type GeoEventPage = { items: GeoEvent[]; total: number; limit: number; offset: number }
export type GeoRoute = {
  id: string
  transaction_id: string
  incident_id: string | null
  origin_event_id: string
  destination_event_id: string
  origin: GeoCoordinate
  destination: GeoCoordinate
  origin_label: string | null
  destination_label: string | null
  amount: string
  currency: string
  transaction_status: 'PENDING' | 'COMPLETED' | 'FAILED'
  transaction_type: 'FUNDING' | 'TRANSFER'
  event_at: string
  synthetic: boolean
  scenario: string | null
  incident_status: IncidentStatus | null
  incident_risk_band: RiskBand | null
  incident_risk_score: number | null
}
export type GeoRoutePage = { items: GeoRoute[]; total: number; limit: number; offset: number }

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, '')

export function getApiConfigurationError() {
  return configuredBaseUrl ? null : 'Set VITE_API_BASE_URL in frontend/.env.local to connect to the FinGuard X API.'
}

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const configurationError = getApiConfigurationError()
  if (configurationError || !configuredBaseUrl) throw new Error(configurationError ?? 'API URL is not configured.')

  let response: Response
  try {
    response = await fetch(`${configuredBaseUrl}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
    })
  } catch {
    throw new Error('FinGuard X API is unavailable. Check that the backend is running, then retry.')
  }

  if (!response.ok) {
    let message = `API request failed (${response.status}).`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch { /* Keep the safe HTTP fallback message. */ }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}
