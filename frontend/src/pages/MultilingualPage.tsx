import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Languages, Play } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { batchMultilingual, getMultilingualStats, processMultilingualTicket } from '@/api'
import { AgentStepTimeline } from '@/components/AgentStepTimeline'
import { AgentResultPanel } from '@/components/AgentResultPanel'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from 'recharts'
import { ChartBox } from '@/components/ChartBox'

export function MultilingualPage() {
  const qc = useQueryClient()
  const [ticketId, setTicketId] = useState('')
  const [batchLang, setBatchLang] = useState('')
  const [lastResult, setLastResult] = useState<Awaited<
    ReturnType<typeof processMultilingualTicket>
  > | null>(null)

  const { data: stats } = useQuery({
    queryKey: ['multilingual-stats'],
    queryFn: getMultilingualStats,
  })

  const processOne = useMutation({
    mutationFn: () => processMultilingualTicket(ticketId.trim()),
    onSuccess: (res) => {
      setLastResult(res)
      toast.success(
        res.translation_skipped
          ? 'Ticket is English — no localization needed'
          : `Agent 1 completed (${res.detected_language_name})`,
      )
      qc.invalidateQueries({ queryKey: ['multilingual-stats'] })
      qc.invalidateQueries({ queryKey: ['ticket', ticketId.trim()] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const batch = useMutation({
    mutationFn: () =>
      batchMultilingual({ language: batchLang || undefined, limit: 50 }),
    onSuccess: (res) => {
      toast.success(
        `Batch complete: ${res.processed} processed, ${res.skipped} skipped`,
      )
      qc.invalidateQueries({ queryKey: ['multilingual-stats'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const gapChart =
    stats?.language_distribution?.map((row: { language: string; total: number }) => ({
      name: row.language,
      count: row.total,
    })) ?? []

  const agentState = lastResult?.agent_state
  const steps = lastResult?.agent_steps ?? agentState?.agent_steps

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Language coverage</h1>
        <p className="text-slate-500">
          Multilingual routing is built into Agent 1 — translate, RAG, and localized replies
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>How it works</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-slate-600">
          <p>
            On every submit or re-run, Agent 1 detects non-English tickets (hi, ta, te, bn, etc.),
            translates the customer message to English for processing, runs the full resolution
            graph, then saves a localized reply plus <strong>message_en</strong> on the ticket.
          </p>
          <p>
            Use this page for coverage stats and to batch re-run Agent 1 on existing non-English
            tickets.
          </p>
        </CardContent>
      </Card>

      {stats && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Language gap report</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {typeof stats.total_non_english_tickets === 'number' && (
                <p>
                  Non-English tickets: <strong>{stats.total_non_english_tickets}</strong>
                  {stats.coverage_pct != null && (
                    <span className="text-slate-500">
                      {' '}
                      · {stats.localized_replies_generated} localized ({stats.coverage_pct}%
                      coverage)
                    </span>
                  )}
                </p>
              )}
              {stats.insight && <p className="text-slate-600">{stats.insight}</p>}
            </CardContent>
          </Card>
          {gapChart.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Tickets by language</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartBox height={220}>
                  <BarChart data={gapChart}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" fill="#8b5cf6" radius={4} />
                  </BarChart>
                </ChartBox>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Languages className="h-5 w-5" />
            Re-run Agent 1 on one ticket
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <label className="flex-1 text-sm">
            Ticket ID
            <input
              className="mt-1 w-full rounded-lg border border-slate-200 p-2 font-mono"
              placeholder="TKT-XXXXXXXX"
              value={ticketId}
              onChange={(e) => setTicketId(e.target.value)}
            />
          </label>
          <Button
            onClick={() => processOne.mutate()}
            disabled={!ticketId.trim() || processOne.isPending}
          >
            {processOne.isPending ? 'Processing…' : 'Re-run Agent 1'}
          </Button>
        </CardContent>
      </Card>

      {lastResult && !lastResult.translation_skipped && (
        <AgentResultPanel
          title={`Localized reply (${lastResult.detected_language_name})`}
          suggestedReply={lastResult.localized_reply ?? agentState?.suggested_reply}
          messageEn={lastResult.message_en ?? agentState?.translated_message}
          englishReply={lastResult.english_reply ?? agentState?.english_reply}
          languageName={lastResult.detected_language_name}
          decision={agentState?.decision}
          reason={agentState?.reason}
          steps={steps}
        />
      )}

      {steps && lastResult?.translation_skipped && (
        <Card>
          <CardContent className="pt-5">
            <AgentStepTimeline steps={steps} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Batch re-run Agent 1 (non-English backlog)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <select
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            value={batchLang}
            onChange={(e) => setBatchLang(e.target.value)}
          >
            <option value="">All non-English</option>
            <option value="hi">Hindi</option>
            <option value="ta">Tamil</option>
            <option value="te">Telugu</option>
            <option value="bn">Bengali</option>
          </select>
          <Button onClick={() => batch.mutate()} disabled={batch.isPending}>
            <Play className="h-4 w-4" />
            {batch.isPending ? 'Running batch…' : 'Re-run Agent 1 (up to 50)'}
          </Button>
        </CardContent>
      </Card>

      <p className="text-sm text-slate-500">
        Tip: open a non-English ticket from the{' '}
        <Link to="/tickets" className="text-brand-600 hover:underline">
          ticket queue
        </Link>{' '}
        and use Re-run Agent 1 on the detail page.
      </p>
    </div>
  )
}
