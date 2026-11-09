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
