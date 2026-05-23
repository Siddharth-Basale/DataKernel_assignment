import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import { AgentStepTimeline } from '@/components/AgentStepTimeline'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { parseAgentSteps } from '@/lib/format'

export function AgentResultPanel({
  decision,
  reason,
  steps,
  suggestedReply,
  resolutionStatus,
  title = 'Agent 1 response',
}: {
  decision?: string
  reason?: string
  steps?: unknown
  suggestedReply?: string
  resolutionStatus?: string
  title?: string
}) {
  const reply = suggestedReply?.trim()
  const parsedSteps = parseAgentSteps(steps)

  return (
    <Card className="border-2 border-brand-200 bg-gradient-to-br from-brand-50/80 to-white shadow-md">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <div className="flex flex-wrap gap-2">
            {decision && <Badge kind="decision" value={decision} />}
            {resolutionStatus && <Badge kind="status" value={resolutionStatus} />}
          </div>
        </div>
        {reason && <p className="text-sm text-slate-600">{reason}</p>}
      </CardHeader>
      <CardContent className="space-y-5">
        {reply ? (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Suggested reply for the customer
              </p>
              <Button
                variant="secondary"
                onClick={() => {
                  navigator.clipboard.writeText(reply)
                  toast.success('Reply copied')
                }}
              >
                <Copy className="h-4 w-4" />
                Copy reply
              </Button>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 text-sm leading-relaxed text-slate-800 whitespace-pre-wrap">
              {reply}
            </div>
          </div>
        ) : (
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            No suggested reply text was returned. Check the agent trace below or re-run Agent 1.
          </p>
        )}

        {parsedSteps.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Agent reasoning steps
            </p>
            <AgentStepTimeline steps={parsedSteps} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
