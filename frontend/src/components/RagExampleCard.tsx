import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { Card, CardContent } from './ui/Card'
import type { RagExample } from '@/types'

export type ScoredRagExample = RagExample & {
  message: string
  agent_reply: string
  similarity: number
}

export function RagExampleCard({
  example,
  index,
}: {
  example: ScoredRagExample
  index: number
}) {
  const [open, setOpen] = useState(false)
  const ex = example

  return (
    <Card
      className={`cursor-pointer border-dashed transition hover:border-brand-400 hover:shadow-md ${
        open ? 'border-brand-400 bg-brand-50/50 ring-2 ring-brand-200' : 'border-brand-200 bg-brand-50/30'
      }`}
      onClick={() => setOpen((v) => !v)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setOpen((v) => !v)
        }
      }}
    >
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center justify-between gap-2">
          <p className="font-medium text-brand-700">RAG match #{index + 1}</p>
          <div className="flex items-center gap-2 text-slate-500">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                ex.similarity >= 70
                  ? 'bg-emerald-100 text-emerald-800'
                  : ex.similarity >= 40
                    ? 'bg-amber-100 text-amber-800'
                    : 'bg-slate-100 text-slate-600'
              }`}
            >
              {ex.similarity}% match
            </span>
            {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </div>
        </div>
        <p className="text-xs text-slate-500">
          {ex.category}
          {ex.sub_category ? ` / ${ex.sub_category}` : ''}
          {ex.ticket_id && (
            <span className="ml-2 font-mono text-slate-400">{ex.ticket_id}</span>
          )}
        </p>
        {!open && ex.message && (
          <p className="line-clamp-2 text-slate-600">{ex.message}</p>
        )}
        {open && (
          <div
            className="space-y-3 border-t border-brand-200/60 pt-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Retrieved context (resolved ticket)
              </p>
              <p className="whitespace-pre-wrap rounded-lg bg-white p-3 text-slate-700">
                {ex.message || '—'}
              </p>
            </div>
            {ex.agent_reply && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Past agent reply
                </p>
                <p className="whitespace-pre-wrap rounded-lg bg-emerald-50/80 p-3 text-slate-800">
                  {ex.agent_reply}
                </p>
              </div>
            )}
            {ex.text && (
              <details className="text-xs">
                <summary className="cursor-pointer text-brand-600">Raw embedding document</summary>
                <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-100 p-2 text-slate-600">
                  {ex.text}
                </pre>
              </details>
            )}
            {ex.distance != null && (
              <p className="text-xs text-slate-400">
                {ex.distance_metric === 'cosine' ? 'Cosine' : 'Vector'} distance:{' '}
                {ex.distance.toFixed(4)}
                {ex.distance_metric === 'cosine' && (
                  <span className="ml-1">(0 = identical, 2 = opposite)</span>
                )}
              </p>
            )}
          </div>
        )}
        {!open && (
          <p className="text-xs text-brand-600">Click to view full RAG context →</p>
        )}
      </CardContent>
    </Card>
  )
}
