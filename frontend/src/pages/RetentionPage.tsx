import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { listRetentionQueue, runAgent3 } from '@/api'
import { AgentStepTimeline } from '@/components/AgentStepTimeline'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { formatInr } from '@/lib/format'

export function RetentionPage() {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState<string | null>(null)
  const [churnThreshold, setChurnThreshold] = useState(3)
  const [lookbackDays, setLookbackDays] = useState(90)
  const [agentSteps, setAgentSteps] = useState<string[]>([])

  const { data: queue } = useQuery({
    queryKey: ['retention'],
    queryFn: () => listRetentionQueue(true, 50),
  })

  const run = useMutation({
    mutationFn: () =>
      runAgent3({
        end_date: '2025-01-31',
        lookback_days: lookbackDays,
        churn_threshold: churnThreshold,
        max_customers: 20,
      }),
    onSuccess: (res) => {
      setAgentSteps(res.agent_steps)
      toast.success(`Queued ${res.selected_count} customers`)
      qc.invalidateQueries({ queryKey: ['retention'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Retention queue</h1>
        <p className="text-slate-500">Agent 3 churn risk & drafted offers</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Run Agent 3</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          <label className="text-sm">
            Lookback days
            <input
              type="number"
              className="mt-1 block w-24 rounded border p-2"
              value={lookbackDays}
              onChange={(e) => setLookbackDays(Number(e.target.value))}
            />
          </label>
          <label className="text-sm">
            Churn threshold
            <input
              type="number"
              step="0.1"
              className="mt-1 block w-24 rounded border p-2"
              value={churnThreshold}
              onChange={(e) => setChurnThreshold(Number(e.target.value))}
            />
          </label>
          <Button onClick={() => run.mutate()} disabled={run.isPending} className="self-end">
            {run.isPending ? 'Scanning…' : 'Build retention queue'}
          </Button>
        </CardContent>
        {agentSteps.length > 0 && (
          <CardContent className="border-t">
            <AgentStepTimeline steps={agentSteps} />
          </CardContent>
        )}
      </Card>

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-5 py-3 text-left">Customer</th>
                <th className="px-5 py-3 text-left">Priority</th>
                <th className="px-5 py-3 text-left">Churn</th>
                <th className="px-5 py-3 text-left">CLV</th>
                <th className="px-5 py-3 text-left">Top issue</th>
                <th className="px-5 py-3 text-left">Open</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody>
              {(queue?.items ?? []).map((row) => (
                <Fragment key={row.queue_id}>
                  <tr className="border-t border-slate-50">
                    <td className="px-5 py-3">
                      <p className="font-medium">{row.customer_name}</p>
                      <Badge kind="tier" value={row.customer_tier} />
                    </td>
                    <td className="px-5 py-3">{row.retention_priority.toFixed(2)}</td>
                    <td className="px-5 py-3">{row.churn_score.toFixed(1)}</td>
                    <td className="px-5 py-3">{formatInr(row.lifetime_value)}</td>
                    <td className="px-5 py-3 capitalize">{row.top_issue}</td>
                    <td className="px-5 py-3">{row.unresolved_count}</td>
                    <td className="px-5 py-3">
                      <Button
                        variant="ghost"
                        onClick={() =>
                          setExpanded(expanded === row.queue_id ? null : row.queue_id)
                        }
                      >
                        Offer
                      </Button>
                    </td>
                  </tr>
                  {expanded === row.queue_id && (
                    <tr key={`${row.queue_id}-offer`}>
                      <td colSpan={7} className="bg-slate-50 px-5 py-4">
                        <p className="whitespace-pre-wrap text-sm">{row.drafted_offer}</p>
                        <div className="mt-3 flex gap-2">
                          <Button
                            variant="secondary"
                            onClick={() => {
                              navigator.clipboard.writeText(row.drafted_offer)
                              toast.success('Copied offer')
                            }}
                          >
                            <Copy className="h-4 w-4" />
                            Copy
                          </Button>
                          <Link
                            to={`/tickets?search=${row.customer_id}`}
                            className="text-sm text-brand-600 hover:underline self-center"
                          >
                            View tickets
                          </Link>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
