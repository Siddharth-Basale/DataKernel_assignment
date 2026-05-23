import { parseAgentSteps } from '@/lib/format'
import { CheckCircle2, Circle } from 'lucide-react'
import { useEffect, useState } from 'react'

export function AgentStepTimeline({
  steps: rawSteps,
  animate = false,
}: {
  steps: unknown
  animate?: boolean
}) {
  const steps = parseAgentSteps(rawSteps)
  const [visible, setVisible] = useState(animate ? 0 : steps.length)

  useEffect(() => {
    if (!animate || steps.length === 0) return
    setVisible(0)
    const timers = steps.map((_, i) =>
      setTimeout(() => setVisible(i + 1), (i + 1) * 600),
    )
    return () => timers.forEach(clearTimeout)
  }, [animate, steps])

  if (steps.length === 0) {
    return <p className="text-sm text-slate-500">No agent steps recorded.</p>
  }

  return (
    <ol className="space-y-3">
      {steps.slice(0, visible).map((step, i) => (
        <li key={i} className="flex gap-3 text-sm">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
          <span className="text-slate-700">{step}</span>
        </li>
      ))}
      {animate && visible < steps.length && (
        <li className="flex gap-3 text-sm text-slate-400">
          <Circle className="mt-0.5 h-4 w-4 shrink-0 animate-pulse" />
          <span>Processing…</span>
        </li>
      )}
    </ol>
  )
}
