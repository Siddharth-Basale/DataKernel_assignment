import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { getCustomerTickets, getTicket, listSkuFlags, runAgent1 } from '@/api'
import type { AgentState } from '@/types'
import { AgentResultPanel } from '@/components/AgentResultPanel'
import { AgentStepTimeline } from '@/components/AgentStepTimeline'
import { SkuIncidentBanner } from '@/components/SkuIncidentBanner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { formatInr, parseAgentSteps, parseJsonArray } from '@/lib/format'

const tabs = ['response', 'overview', 'agent', 'history'] as const

export function TicketDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [tab, setTab] = useState<(typeof tabs)[number]>('response')
  const [lastRun, setLastRun] = useState<AgentState | null>(null)
  const qc = useQueryClient()

  const { data: ticket, isLoading } = useQuery({
    queryKey: ['ticket', id],
    queryFn: () => getTicket(id!),
    enabled: !!id,
  })

  useEffect(() => {
    if (ticket?.agent_decision || ticket?.suggested_reply) {
      setTab('response')
    }
  }, [ticket?.ticket_id, ticket?.agent_decision, ticket?.suggested_reply])

  const { data: history } = useQuery({
    queryKey: ['customer-tickets', ticket?.customer_id],
    queryFn: () => getCustomerTickets(ticket!.customer_id!),
    enabled: !!ticket?.customer_id,
  })

  const { data: skuFlags } = useQuery({
    queryKey: ['sku-flags'],
    queryFn: () => listSkuFlags(true),
  })

  const rerun = useMutation({
    mutationFn: () => runAgent1(id!),
    onSuccess: (data) => {
      setLastRun(data.agent_state)
      setTab('response')
      toast.success('Agent 1 completed')
      qc.invalidateQueries({ queryKey: ['ticket', id] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const activeFlag = skuFlags?.items.find((f) => f.product_sku === ticket?.product_sku)
  const entities = parseJsonArray<string>(ticket?.key_entities)
  const steps = parseAgentSteps(lastRun?.agent_steps ?? ticket?.agent_steps)

  const agentState = lastRun
  const displayReply =
    agentState?.localized_reply ??
    agentState?.suggested_reply ??
    ticket?.suggested_reply ??
    ticket?.agent_reply
  const displayDecision = agentState?.decision ?? ticket?.agent_decision
  const displayReason = agentState?.reason ?? ticket?.agent_reason
  const messageEn = agentState?.translated_message ?? ticket?.message_en
  const englishReply = agentState?.english_reply
  const languageName = agentState?.detected_language_name

  if (isLoading || !ticket) {
    return <div className="h-64 animate-pulse rounded-xl bg-slate-100" />
  }

  const messageText = ticket.message?.trim() ?? ''
  const summaryText = ticket.summary?.trim() ?? ''
  const showSummary =
    summaryText.length > 0 &&
    summaryText !== messageText &&
    !messageText.includes(summaryText) &&
    !summaryText.includes(messageText)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/tickets" className="text-sm text-brand-600 hover:underline">
            ← Tickets
          </Link>
          <h1 className="mt-2 font-mono text-2xl font-semibold">{ticket.ticket_id}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge kind="status" value={ticket.resolution_status} />
            <Badge kind="tier" value={ticket.customer_tier} />
            {ticket.language && ticket.language !== 'en' && (
              <Badge kind="default" value={ticket.language} />
            )}
            {displayDecision && <Badge kind="decision" value={displayDecision} />}
          </div>
        </div>
        <Button variant="secondary" onClick={() => rerun.mutate()} disabled={rerun.isPending}>
          <RefreshCw className={`h-4 w-4 ${rerun.isPending ? 'animate-spin' : ''}`} />
          Re-run Agent 1
        </Button>
      </div>

      {activeFlag && <SkuIncidentBanner flag={activeFlag} />}

      {(displayDecision || displayReply) && tab !== 'response' && (
        <button
          type="button"
          onClick={() => setTab('response')}
          className="w-full rounded-lg border border-brand-200 bg-brand-50 px-4 py-2 text-left text-sm text-brand-800 hover:bg-brand-100"
        >
          Agent 1 finished — click to view suggested reply and reasoning →
        </button>
      )}

      <div className="flex flex-wrap gap-2 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`border-b-2 px-4 py-2 text-sm font-medium capitalize ${
              tab === t
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {t === 'response' ? 'Agent response' : t}
          </button>
        ))}
      </div>

      {tab === 'response' && (
        <AgentResultPanel
          decision={displayDecision}
          reason={displayReason}
          steps={steps}
          suggestedReply={displayReply}
          messageEn={messageEn}
          englishReply={englishReply}
          languageName={languageName}
          resolutionStatus={ticket.resolution_status}
        />
      )}

      {tab === 'overview' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Customer message</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {messageText ? (
                <p className="whitespace-pre-wrap text-slate-700">{ticket.message}</p>
              ) : (
                <p className="text-slate-400">No message on file.</p>
              )}
              {ticket.message_en?.trim() &&
                ticket.message_en.trim() !== messageText && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <p className="mb-1 text-xs font-semibold uppercase text-slate-500">
                      English translation
                    </p>
                    <p className="whitespace-pre-wrap text-slate-700">{ticket.message_en}</p>
                  </div>
                )}
              {showSummary && (
                <div className="rounded-lg border border-slate-100 bg-slate-50/80 p-3">
                  <p className="mb-1 text-xs font-semibold uppercase text-slate-500">Summary</p>
                  <p className="whitespace-pre-wrap text-slate-600">{ticket.summary}</p>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {entities.map((e) => (
                  <span key={e} className="rounded-full bg-slate-100 px-2 py-1 text-xs">
                    {e}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Order & scores</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-slate-500">Order</p>
                <p className="font-mono">{ticket.order_id}</p>
              </div>
              <div>
                <p className="text-slate-500">Value</p>
                <p>{formatInr(ticket.order_value)}</p>
              </div>
              <div>
                <p className="text-slate-500">SKU</p>
                <p className="font-mono text-xs">{ticket.product_sku}</p>
              </div>
              <div>
                <p className="text-slate-500">Channel</p>
                <p>{ticket.channel}</p>
              </div>
              <div>
                <p className="text-slate-500">Sentiment</p>
                <p>{ticket.sentiment_score}</p>
              </div>
              <div>
                <p className="text-slate-500">Revenue at risk</p>
                <p className="text-red-600">{formatInr(ticket.revenue_at_risk)}</p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {tab === 'agent' && (
        <Card>
          <CardHeader>
            <CardTitle>Full agent trace</CardTitle>
          </CardHeader>
          <CardContent>
            <AgentStepTimeline steps={steps} animate={rerun.isPending} />
          </CardContent>
        </Card>
      )}

      {tab === 'history' && (
        <Card>
          <CardHeader>
            <CardTitle>Customer history</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(history?.items ?? []).map((t) => (
              <Link
                key={t.ticket_id}
                to={`/tickets/${t.ticket_id}`}
                className="flex items-center justify-between rounded-lg border border-slate-100 p-3 text-sm hover:bg-slate-50"
              >
                <span className="font-mono text-brand-600">{t.ticket_id}</span>
                <Badge kind="status" value={t.resolution_status} />
              </Link>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
