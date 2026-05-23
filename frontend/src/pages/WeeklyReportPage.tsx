import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Play } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import {
  getLatestWeeklyReportHtml,
  listWeeklyReports,
  runWeeklyReport,
} from '@/api'
import { AgentStepTimeline } from '@/components/AgentStepTimeline'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'

export function WeeklyReportPage() {
  const qc = useQueryClient()
  const [weekStart, setWeekStart] = useState('')
  const [previewHtml, setPreviewHtml] = useState<string | null>(null)
  const [agentSteps, setAgentSteps] = useState<string[]>([])

  const { data: reportList } = useQuery({
    queryKey: ['weekly-reports'],
    queryFn: listWeeklyReports,
  })

  const run = useMutation({
    mutationFn: () => runWeeklyReport(weekStart || undefined),
    onSuccess: async (res) => {
      setAgentSteps(res.agent_steps ?? [])
      toast.success('Weekly report generated')
      qc.invalidateQueries({ queryKey: ['weekly-reports'] })
      try {
        const html = await getLatestWeeklyReportHtml()
        setPreviewHtml(html)
      } catch {
        toast.message('Report saved — open preview after refresh')
      }
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const loadPreview = useMutation({
    mutationFn: getLatestWeeklyReportHtml,
    onSuccess: (html) => setPreviewHtml(html),
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Weekly insight report</h1>
        <p className="text-slate-500">
          Agent 4 — leadership KPIs, week-over-week trends, and narrative (assignment deliverable)
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>When Agent 4 runs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-slate-600">
          <p>
            Automatically on a weekly schedule, or manually below. It pulls ticket KPIs, compares
            to the prior week, includes active incidents from Agent 2 and churn summary from Agent
            3, then writes an executive HTML report.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Generate report</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-4">
          <label className="text-sm">
            Week start (Monday, optional)
            <input
              type="date"
              className="mt-1 block rounded-lg border border-slate-200 p-2"
              value={weekStart}
              onChange={(e) => setWeekStart(e.target.value)}
            />
          </label>
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            <Play className="h-4 w-4" />
            {run.isPending ? 'Generating…' : 'Run Agent 4'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => loadPreview.mutate()}
            disabled={loadPreview.isPending}
          >
            <FileText className="h-4 w-4" />
            Load latest preview
          </Button>
        </CardContent>
        {agentSteps.length > 0 && (
          <CardContent className="border-t">
            <AgentStepTimeline steps={agentSteps} />
          </CardContent>
        )}
      </Card>

      {reportList?.reports && reportList.reports.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Past reports</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {reportList.reports.map((r) => (
              <div
                key={r.report_id}
                className="flex justify-between rounded-lg border border-slate-100 px-3 py-2"
              >
                <span className="font-mono text-slate-600">{r.report_id}</span>
                <span>
                  {r.week_start} → {r.week_end}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {previewHtml && (
        <Card>
          <CardHeader>
            <CardTitle>Report preview</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <iframe
              title="Weekly report"
              srcDoc={previewHtml}
              className="h-[70vh] w-full rounded-b-xl border-0"
              sandbox="allow-same-origin"
            />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
