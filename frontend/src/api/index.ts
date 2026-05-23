import { api } from './client'
import type {
  AgentState,
  Incident,
  InsightsResponse,
  RetentionItem,
  SetupStatus,
  SkuFlag,
  Ticket,
  TicketDraftRequest,
  TicketDraftResponse,
  TicketFilters,
  TicketSubmitResponse,
  TrendPoint,
} from '@/types'

export async function getHealth() {
  const { data } = await api.get<{ status: string; database: string; tickets: number }>(
    '/health',
  )
  return data
}

export async function getSetup(): Promise<SetupStatus> {
  const { data } = await api.get<SetupStatus>('/system/setup')
  return data
}

export async function seedDatabase(refreshVectors = true, maxVectors?: number) {
  const params: Record<string, string | number | boolean> = { refresh_vectors: refreshVectors }
  if (maxVectors != null) params.max_vectors = maxVectors
  const { data } = await api.post('/seed', null, { params })
  return data
}

export async function getInsights(): Promise<InsightsResponse> {
  const { data } = await api.get<InsightsResponse>('/insights')
  return data
}

export async function getInsightsTrends(granularity = 'week') {
  const { data } = await api.get<{
    granularity: string
    points: TrendPoint[]
  }>('/insights/trends', { params: { granularity } })
  return data
}

export async function listTickets(params: {
  limit?: number
  offset?: number
  category?: string
  status?: string
  frustration?: string
  agent_decision?: string
}) {
  const { data } = await api.get<{
    total: number
    limit: number
    offset: number
    items: Ticket[]
  }>('/tickets', { params })
  return data
}

export async function searchTickets(q: string, limit = 20) {
  const { data } = await api.get<{ query: string; total: number; items: Ticket[] }>(
    '/tickets/search',
    { params: { q, limit } },
  )
  return data
}

export async function getTicketFilters(): Promise<TicketFilters> {
  const { data } = await api.get<TicketFilters>('/tickets/filters')
  return data
}

export async function getTicket(ticketId: string): Promise<Ticket> {
  const { data } = await api.get<Ticket>(`/tickets/${ticketId}`)
  return data
}

export async function getCustomerTickets(customerId: string, limit = 50) {
  const { data } = await api.get<{ customer_id: string; total: number; items: Ticket[] }>(
    `/customers/${encodeURIComponent(customerId)}/tickets`,
    { params: { limit } },
  )
  return data
}

export async function draftTicket(payload: TicketDraftRequest): Promise<TicketDraftResponse> {
  const { data } = await api.post<TicketDraftResponse>('/tickets/draft', payload)
  return data
}

export async function submitTicket(
  payload: Record<string, unknown>,
): Promise<TicketSubmitResponse> {
  const { data } = await api.post<TicketSubmitResponse>('/tickets/submit', payload)
  return data
}

export async function runAgent1(ticketId: string) {
  const { data } = await api.post<{ ticket_id: string; agent_state: AgentState }>(
    `/agent1/run/${ticketId}`,
  )
  return data
}

export async function runAgent2(params: {
  threshold?: number
  max_incidents?: number
  start_date?: string
  end_date?: string
}) {
  const { data } = await api.post<{
    incidents: Incident[]
    agent_steps: string[]
    candidate_count: number
  }>('/agent2/run', null, { params })
  return data
}

export async function listIncidents(activeOnly = true, limit = 20) {
  const { data } = await api.get<{ total: number; items: Incident[] }>('/agent2/incidents', {
    params: { active_only: activeOnly, limit },
  })
  return data
}

export async function listSkuFlags(activeOnly = true) {
  const { data } = await api.get<{ total: number; items: SkuFlag[] }>('/agent2/sku-flags', {
    params: { active_only: activeOnly },
  })
  return data
}

export async function runAgent3(params: {
  end_date?: string
  lookback_days?: number
  min_ticket_count?: number
  churn_threshold?: number
  max_customers?: number
}) {
  const { data } = await api.post<{
    retention_queue: RetentionItem[]
    agent_steps: string[]
    selected_count: number
    window_start: string
    window_end: string
  }>('/agent3/run', null, { params })
  return data
}

export async function listRetentionQueue(activeOnly = true, limit = 20) {
  const { data } = await api.get<{ total: number; items: RetentionItem[] }>(
    '/agent3/retention-queue',
    { params: { active_only: activeOnly, limit } },
  )
  return data
}

export interface WeeklyReportMeta {
  report_id: string
  week_start: string
  week_end: string
  created_at: string
}

export async function runWeeklyReport(weekStart?: string) {
  const { data } = await api.post<{
    report_id: string
    week_start: string
    week_end: string
    report_path: string
    kpis: Record<string, unknown>
    narrative: string
    agent_steps: string[]
  }>('/api/agents/weekly-report/run', null, {
    params: weekStart ? { week_start: weekStart } : {},
  })
  return data
}

export async function listWeeklyReports() {
  const { data } = await api.get<{ reports: WeeklyReportMeta[] }>(
    '/api/agents/weekly-report/list',
  )
  return data
}

export async function getLatestWeeklyReportHtml() {
  const { data } = await api.get<string>('/api/agents/weekly-report/latest', {
    responseType: 'text',
  })
  return data
}

export async function processMultilingualTicket(ticketId: string) {
  const { data } = await api.post<{
    ticket_id: string
    agent_state?: import('@/types').AgentState
    detected_language?: string
    detected_language_name?: string
    translation_skipped?: boolean
    message_en?: string
    english_reply?: string
    localized_reply?: string
    agent_steps?: string[]
    error?: string
  }>(`/api/agents/multilingual/process/${ticketId}`)
  return data
}

export async function batchMultilingual(params?: { language?: string; limit?: number }) {
  const { data } = await api.post<{
    processed: number
    skipped: number
    errors: string[]
    ticket_ids: string[]
  }>('/api/agents/multilingual/batch', null, { params })
  return data
}

export async function getMultilingualStats() {
  const { data } = await api.get<{
    language_distribution: {
      language: string
      total: number
      has_reply: number
      avg_sentiment: number
    }[]
    total_non_english_tickets: number
    localized_replies_generated: number
    coverage_pct: number
    insight: string
  }>('/api/agents/multilingual/stats')
  return data
}
