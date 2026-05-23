import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Circle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { getHealth, getSetup, seedDatabase } from '@/api'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { KpiCard } from '@/components/KpiCard'

export function SetupPage() {
  const qc = useQueryClient()
  const [refreshVectors, setRefreshVectors] = useState(true)
  const [maxVectors, setMaxVectors] = useState(500)

  const { data: setup } = useQuery({ queryKey: ['setup'], queryFn: getSetup })
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth })

  const seed = useMutation({
    mutationFn: () => seedDatabase(refreshVectors, maxVectors),
    onSuccess: (data) => {
      toast.success(`Loaded ${data.rows_loaded} rows`)
      qc.invalidateQueries()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const checklist = [
    { ok: setup?.dataset_exists, label: 'dataset.csv present' },
    { ok: setup?.seeded, label: 'SQLite seeded' },
    { ok: setup?.vectors_ready, label: 'Chroma vectors ready' },
    { ok: setup?.openai_configured, label: 'OpenAI API key configured' },
  ]

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Setup</h1>
        <p className="text-slate-500">Seed the database and vector store for demos</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <KpiCard label="Tickets in DB" value={String(health?.tickets ?? 0)} />
        <KpiCard label="Vectors" value={String(setup?.vector_count ?? 0)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Checklist</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {checklist.map(({ ok, label }) => (
            <div key={label} className="flex items-center gap-2 text-sm">
              {ok ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              ) : (
                <Circle className="h-4 w-4 text-slate-300" />
              )}
              <span className={ok ? 'text-slate-700' : 'text-slate-400'}>{label}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Seed dataset</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={refreshVectors}
              onChange={(e) => setRefreshVectors(e.target.checked)}
            />
            Refresh Chroma vectors after load
          </label>
          <div>
            <label className="text-sm text-slate-600">
              Max vectors (cost cap): {maxVectors}
            </label>
            <input
              type="range"
              min={100}
              max={2000}
              step={100}
              value={maxVectors}
              onChange={(e) => setMaxVectors(Number(e.target.value))}
              className="mt-2 w-full"
            />
          </div>
          <Button onClick={() => seed.mutate()} disabled={seed.isPending}>
            {seed.isPending ? 'Seeding…' : 'Run POST /seed'}
          </Button>
          {seed.data && (
            <pre className="overflow-auto rounded-lg bg-slate-50 p-3 text-xs">
              {JSON.stringify(seed.data, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
