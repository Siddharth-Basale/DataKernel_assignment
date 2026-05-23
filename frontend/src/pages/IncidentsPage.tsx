import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { listIncidents, listSkuFlags, runAgent2 } from '@/api'
import { AgentStepTimeline } from '@/components/AgentStepTimeline'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import type { Incident } from '@/types'

export function IncidentsPage() {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState<string | null>(null)
  const [threshold, setThreshold] = useState(2)
  const [maxIncidents, setMaxIncidents] = useState(3)
  const [agentSteps, setAgentSteps] = useState<string[]>([])
  const [lastRunIncidents, setLastRunIncidents] = useState<Incident[]>([])

  const { data: incidents } = useQuery({
    queryKey: ['incidents'],
    queryFn: () => listIncidents(true, 20),
  })
  const { data: skuFlags } = useQuery({
    queryKey: ['sku-flags'],
    queryFn: () => listSkuFlags(true),
  })

  const run = useMutation({
    mutationFn: () =>
      runAgent2({
        threshold,
        max_incidents: maxIncidents,
        start_date: '2024-07-01',
        end_date: '2025-01-31',
      }),
    onSuccess: (res) => {
      setAgentSteps(res.agent_steps)
      setLastRunIncidents(res.incidents)
      toast.success(`Created ${res.incidents.length} incidents`)
      qc.invalidateQueries({ queryKey: ['incidents'] })
      qc.invalidateQueries({ queryKey: ['sku-flags'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Incidents</h1>
        <p className="text-slate-500">Agent 2 anomaly investigation — Z-score spikes & SKU flags</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Run Agent 2</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-4">
          <label className="text-sm">
            Z-score threshold
            <input
              type="number"
              step="0.1"
              className="mt-1 block w-24 rounded border p-2"
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
            />
          </label>
          <label className="text-sm">
            Max incidents
            <input
              type="number"
              className="mt-1 block w-24 rounded border p-2"
              value={maxIncidents}
              onChange={(e) => setMaxIncidents(Number(e.target.value))}
            />
          </label>
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? 'Investigating…' : 'Run investigation'}
          </Button>
        </CardContent>
        {agentSteps.length > 0 && (
          <CardContent className="space-y-4 border-t">
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700">Agent 2 run log</p>
              <AgentStepTimeline steps={agentSteps} animate />
            </div>
            {lastRunIncidents.length > 0 && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-4">
                <p className="mb-2 text-sm font-medium text-emerald-900">
                  Incidents created this run ({lastRunIncidents.length})
                </p>
                <ul className="list-inside list-disc text-sm text-emerald-800">
                  {lastRunIncidents.map((inc) => (
                    <li key={inc.incident_id}>{inc.title}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        )}
      </Card>

      <div className="space-y-4">
        {(incidents?.items ?? []).map((inc: Incident) => (
          <Card key={inc.incident_id}>
            <CardHeader
              className="cursor-pointer"
              onClick={() =>
                setExpanded(expanded === inc.incident_id ? null : inc.incident_id)
              }
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Badge kind="severity" value={inc.severity} />
                  <CardTitle>{inc.title}</CardTitle>
                </div>
                {expanded === inc.incident_id ? (
                  <ChevronUp className="h-5 w-5" />
                ) : (
                  <ChevronDown className="h-5 w-5" />
                )}
              </div>
              <p className="text-sm text-slate-500">
                {inc.category} · {inc.start_date} – {inc.end_date} · z={inc.z_score?.toFixed(2)} ·{' '}
                {inc.ticket_count} tickets
              </p>
            </CardHeader>
            {expanded === inc.incident_id && (
              <CardContent className="space-y-4 border-t text-sm">
                <p>{inc.pattern}</p>
                <p>
                  <strong>Root cause:</strong> {inc.root_cause}
                </p>
                <p>
                  <strong>Action:</strong> {inc.recommended_action}
                </p>
                {inc.report && (
                  <pre className="whitespace-pre-wrap rounded-lg bg-slate-50 p-4 text-xs">
                    {inc.report}
                  </pre>
                )}
                <div className="flex flex-wrap gap-2">
                  {(inc.sample_ticket_ids ?? []).map((tid) => (
                    <Link
                      key={tid}
                      to={`/tickets/${tid}`}
                      className="font-mono text-brand-600 hover:underline"
                    >
                      {tid}
                    </Link>
                  ))}
                </div>
              </CardContent>
            )}
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Flagged SKUs (Agent 1 reads these)</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="pb-2">SKU</th>
                <th className="pb-2">Incident</th>
                <th className="pb-2">Severity</th>
                <th className="pb-2">Category</th>
              </tr>
            </thead>
            <tbody>
              {(skuFlags?.items ?? []).map((f) => (
                <tr key={f.product_sku} className="border-t border-slate-50">
                  <td className="py-2 font-mono">{f.product_sku}</td>
                  <td className="py-2">{f.incident_id}</td>
                  <td className="py-2">
                    <Badge kind="severity" value={f.severity} />
                  </td>
                  <td className="py-2">{f.category}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
