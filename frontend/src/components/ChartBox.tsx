import type { ReactNode } from 'react'
import { ResponsiveContainer } from 'recharts'

/** Recharts needs a parent with explicit pixel height; h-64 + height 100% often yields -1. */
export function ChartBox({
  height = 256,
  children,
}: {
  height?: number
  children: ReactNode
}) {
  return (
    <div className="w-full min-w-0" style={{ height }}>
      <ResponsiveContainer width="100%" height={height}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}
