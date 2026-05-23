import { Card, CardContent } from './ui/Card'
import { cn } from '@/lib/utils'

export function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: 'danger' | 'warning' | 'neutral'
}) {
  return (
    <Card>
      <CardContent className="space-y-1">
        <p className="text-sm text-slate-500">{label}</p>
        <p
          className={cn(
            'text-2xl font-semibold tracking-tight',
            accent === 'danger' && 'text-red-600',
            accent === 'warning' && 'text-amber-600',
            !accent && 'text-slate-900',
          )}
        >
          {value}
        </p>
        {sub && <p className="text-xs text-slate-400">{sub}</p>}
      </CardContent>
    </Card>
  )
}
