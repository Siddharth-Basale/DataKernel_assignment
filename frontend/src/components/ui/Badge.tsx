import { cn } from '@/lib/utils'

const tierStyles: Record<string, string> = {
  regular: 'bg-slate-100 text-slate-700',
  prime: 'bg-blue-100 text-blue-800',
  prime_plus: 'bg-amber-100 text-amber-900',
}

const frustrationStyles: Record<string, string> = {
  low: 'bg-emerald-100 text-emerald-800',
  medium: 'bg-yellow-100 text-yellow-800',
  high: 'bg-orange-100 text-orange-800',
  critical: 'bg-red-100 text-red-800',
}

const statusStyles: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  resolved: 'bg-emerald-100 text-emerald-800',
  escalated: 'bg-red-100 text-red-800',
  unresolved: 'bg-slate-200 text-slate-700',
}

const decisionStyles: Record<string, string> = {
  suggest_reply: 'bg-blue-100 text-blue-800',
  auto_resolve: 'bg-emerald-100 text-emerald-800',
  escalate: 'bg-red-100 text-red-800',
}

const severityStyles: Record<string, string> = {
  low: 'bg-slate-100 text-slate-600',
  medium: 'bg-yellow-100 text-yellow-800',
  high: 'bg-orange-100 text-orange-800',
  critical: 'bg-red-100 text-red-800',
}

export function Badge({
  children,
  kind = 'default',
  value,
  className,
}: {
  children?: React.ReactNode
  kind?: 'tier' | 'frustration' | 'status' | 'decision' | 'severity' | 'default'
  value?: string
  className?: string
}) {
  const label = children ?? value ?? ''
  const key = String(value ?? label).toLowerCase()
  let style = 'bg-slate-100 text-slate-700'
  if (kind === 'tier') style = tierStyles[key] ?? style
  if (kind === 'frustration') style = frustrationStyles[key] ?? style
  if (kind === 'status') style = statusStyles[key] ?? style
  if (kind === 'decision') style = decisionStyles[key] ?? style
  if (kind === 'severity') style = severityStyles[key] ?? style

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize',
        style,
        className,
      )}
    >
      {label}
    </span>
  )
}
