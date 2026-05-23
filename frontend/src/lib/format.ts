export function formatInr(value: number | undefined | null): string {
  const n = Number(value ?? 0)
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(n)
}

export function formatInrCrore(value: number | undefined | null): string {
  const n = Number(value ?? 0)
  const crore = n / 1e7
  if (crore >= 0.01) return `₹${crore.toFixed(2)} Cr`
  return formatInr(n)
}

export function formatRelativeTime(ts?: string): string {
  if (!ts) return '—'
  const date = new Date(ts.replace(' ', 'T'))
  const diff = Date.now() - date.getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return date.toLocaleDateString('en-IN')
}

export function parseJsonArray<T = string>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[]
  if (typeof value === 'string' && value.trim()) {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : [value as T]
    } catch {
      return value.split(',').map((s) => s.trim()) as T[]
    }
  }
  return []
}

export function parseAgentSteps(value: unknown): string[] {
  return parseJsonArray<string>(value)
}
