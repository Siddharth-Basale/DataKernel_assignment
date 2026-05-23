export interface Ticket {
  ticket_id: string
  timestamp?: string
  customer_id?: string
  customer_name?: string
  customer_tier?: string
  channel?: string
  customer_country?: string
  language?: string
  product_category?: string
  product_sku?: string
  order_id?: string
  order_date?: string
  order_value?: number
  message?: string
  agent_reply?: string
  resolution_status?: string
  resolution_time_hrs?: number
  is_repeat_contact?: string | boolean
  category?: string
  sub_category?: string
  sentiment_score?: number
  frustration_level?: string
  urgency_score?: number
  revenue_at_risk?: number
  summary?: string
  key_entities?: string | string[]
  suggested_reply?: string
  agent_decision?: string
  agent_reason?: string
  agent_steps?: string | string[]
  suggested_fields_reason?: string
  rag_examples?: RagExample[]
}

export interface RagExample {
  ticket_id?: string
  message?: string
  category?: string
  sub_category?: string
  agent_reply?: string
  /** Chroma document: "Customer message: ...\nAgent reply: ..." */
  text?: string
  distance?: number
  /** Server-computed 0–100 match score (preferred over client-side guess). */
  similarity_percent?: number
  distance_metric?: string
  similarity?: number
}

export interface TicketDraftRequest {
  message: string
  customer_tier: string
  product_sku: string
  order_value: number
  customer_name?: string
  customer_id?: string
  channel?: string
  customer_country?: string
  language?: string
  product_category?: string
  order_id?: string
  order_date?: string
  summary?: string
}

export interface TicketDraftResponse {
  draft: Ticket
  submit_payload: Record<string, unknown>
  next_step: string
}

export interface AgentState {
  decision?: string
  reason?: string
  agent_steps?: string[]
  suggested_reply?: string
  similar_tickets?: unknown[]
  ticket?: Ticket
}

export interface TicketSubmitResponse {
  ticket_id: string
  stored_ticket: Ticket
  agent_state: AgentState
}

export interface CountItem {
  name: string
  count: number
}

export interface InsightsResponse {
  totals: {
    ticket_count?: number
    unresolved_count?: number
    revenue_at_risk?: number
    avg_sentiment?: number
    avg_urgency?: number
  }
  top_categories: CountItem[]
  top_sub_categories: CountItem[]
  language_distribution: CountItem[]
  status_distribution: CountItem[]
  sentiment_by_category: {
    category: string
    tickets: number
    avg_sentiment: number
    revenue_at_risk: number
  }[]
}

export interface TrendPoint {
  period?: string
  day?: string
  avg_sentiment: number
  ticket_count: number
  revenue_at_risk: number
}

export interface Incident {
  incident_id: string
  title: string
  severity: string
  category: string
  affected_sku?: string
  start_date?: string
  end_date?: string
  z_score?: number
  ticket_count?: number
  top_skus?: [string, number][] | string[]
  pattern?: string
  root_cause?: string
  recommended_action?: string
  sample_ticket_ids?: string[]
  report?: string
  active?: boolean
}

export interface SkuFlag {
  product_sku: string
  incident_id: string
  category: string
  severity: string
  active_incident: boolean
  updated_at?: string
}

export interface RetentionItem {
  queue_id: string
  customer_id: string
  customer_name: string
  customer_tier: string
  customer_country?: string
  language?: string
  ticket_count: number
  unresolved_count: number
  is_repeat: boolean
  top_issue: string
  churn_score: number
  lifetime_value: number
  retention_priority: number
  drafted_offer: string
  window_start?: string
  window_end?: string
}

export interface SetupStatus {
  seeded: boolean
  ticket_count: number
  incident_count: number
  vectors_ready: boolean
  vector_count: number
  openai_configured: boolean
  database: string
  dataset_exists: boolean
}

export interface TicketFilters {
  category: string[]
  resolution_status: string[]
  customer_tier: string[]
  frustration_level: string[]
  channel: string[]
  agent_decision: string[]
}
