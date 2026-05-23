import { useQuery } from '@tanstack/react-query'
import { Plus, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getTicketFilters, listTickets, searchTickets } from '@/api'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { formatInr, formatRelativeTime } from '@/lib/format'
import type { TicketFilters } from '@/types'

const DEFAULT_FILTERS: TicketFilters = {
  category: [],
  resolution_status: ['pending', 'resolved', 'unresolved', 'escalated'],
  customer_tier: [],
  frustration_level: ['low', 'medium', 'high', 'critical'],
  channel: [],
  agent_decision: ['suggest_reply', 'auto_resolve', 'escalate'],
}

export function TicketsPage() {
  const [params, setParams] = useSearchParams()
  const [searchQ, setSearchQ] = useState(params.get('q') ?? '')
  const category = params.get('category') ?? ''
  const status = params.get('status') ?? ''
  const frustration = params.get('frustration') ?? ''
  const agentDecision = params.get('agent_decision') ?? ''
  const offset = Number(params.get('offset') ?? 0)
  const limit = 20

  const { data: filters } = useQuery({
    queryKey: ['ticket-filters'],
    queryFn: getTicketFilters,
    retry: 2,
    staleTime: 60_000,
  })
  const f = filters ?? DEFAULT_FILTERS

  useEffect(() => {
    const t = setTimeout(() => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (searchQ.trim().length >= 2) next.set('q', searchQ.trim())
          else next.delete('q')
          next.set('offset', '0')
          return next
        },
        { replace: true },
      )
    }, 400)
    return () => clearTimeout(t)
  }, [searchQ, setParams])

  const q = params.get('q') ?? ''
  const searching = q.length >= 2

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['tickets', category, status, frustration, agentDecision, offset, q],
    queryFn: () =>
      searching
        ? searchTickets(q, limit).then((r) => ({
            total: r.total,
            limit,
            offset: 0,
            items: r.items,
          }))
        : listTickets({
            limit,
            offset,
            category: category || undefined,
            status: status || undefined,
            frustration: frustration || undefined,
            agent_decision: agentDecision || undefined,
          }),
  })

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.set('offset', '0')
    setParams(next)
  }

  const clearFilters = () => {
    setSearchQ('')
    setParams({})
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Ticket queue</h1>
          <p className="text-slate-500">
            {data?.total?.toLocaleString() ?? 0} matching tickets
            {isError && (
              <span className="ml-2 text-red-600">· {(error as Error).message}</span>
            )}
          </p>
        </div>
        <Link to="/tickets/new">
          <Button>
            <Plus className="h-4 w-4" />
            New ticket
          </Button>
        </Link>
      </div>

      <Card>
        <CardContent className="space-y-3 pt-5">
          <div className="relative min-w-[200px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm"
              placeholder="Search ticket ID, customer, message, SKU…"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <select
              className="min-w-[140px] rounded-lg border border-slate-200 px-3 py-2 text-sm"
              value={category}
              onChange={(e) => setFilter('category', e.target.value)}
            >
              <option value="">All categories</option>
              {f.category.map((c) => (
                <option key={c} value={c}>
                  {c.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <select
              className="min-w-[130px] rounded-lg border border-slate-200 px-3 py-2 text-sm"
              value={status}
              onChange={(e) => setFilter('status', e.target.value)}
            >
              <option value="">All statuses</option>
              {f.resolution_status.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              className="min-w-[130px] rounded-lg border border-slate-200 px-3 py-2 text-sm"
              value={frustration}
              onChange={(e) => setFilter('frustration', e.target.value)}
            >
              <option value="">All frustration</option>
              {f.frustration_level.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              className="min-w-[150px] rounded-lg border border-slate-200 px-3 py-2 text-sm"
              value={agentDecision}
              onChange={(e) => setFilter('agent_decision', e.target.value)}
            >
              <option value="">All agent outcomes</option>
              {f.agent_decision.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            {(category || status || frustration || agentDecision || q) && (
              <Button variant="ghost" onClick={clearFilters}>
                Clear filters
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tickets</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="border-b border-slate-100 bg-slate-50 text-slate-500">
              <tr>
                <th className="px-5 py-3 font-medium">ID</th>
                <th className="px-5 py-3 font-medium">Customer</th>
                <th className="px-5 py-3 font-medium">Issue</th>
                <th className="px-5 py-3 font-medium">Frustration</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium">Agent</th>
                <th className="px-5 py-3 font-medium">Risk</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="px-5 py-8 text-center text-slate-400">
                    Loading…
                  </td>
                </tr>
              ) : data?.items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-8 text-center text-slate-400">
                    No tickets match these filters.
                  </td>
                </tr>
              ) : (
                data?.items.map((t) => (
                  <tr
                    key={t.ticket_id}
                    className="border-b border-slate-50 hover:bg-slate-50/80"
                  >
                    <td className="px-5 py-3">
                      <Link
                        to={`/tickets/${t.ticket_id}`}
                        className="font-mono text-brand-600 hover:underline"
                      >
                        {t.ticket_id}
                      </Link>
                      <p className="text-xs text-slate-400">{formatRelativeTime(t.timestamp)}</p>
                    </td>
                    <td className="px-5 py-3">
                      <p className="font-medium">{t.customer_name}</p>
                      <Badge kind="tier" value={t.customer_tier} />
                    </td>
                    <td className="px-5 py-3 max-w-[200px]">
                      <p className="capitalize">{t.category?.replace(/_/g, ' ')}</p>
                      <p className="text-xs text-slate-500 line-clamp-1">{t.sub_category}</p>
                    </td>
                    <td className="px-5 py-3">
                      <Badge kind="frustration" value={t.frustration_level} />
                    </td>
                    <td className="px-5 py-3">
                      <Badge kind="status" value={t.resolution_status} />
                    </td>
                    <td className="px-5 py-3">
                      {t.agent_decision ? (
                        <Badge kind="decision" value={t.agent_decision} />
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-5 py-3">
                      {Number(t.revenue_at_risk) > 0 ? formatInr(t.revenue_at_risk) : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
        {!searching && (data?.total ?? 0) > limit && (
          <div className="flex justify-between border-t border-slate-100 px-5 py-3">
            <Button
              variant="secondary"
              disabled={offset === 0}
              onClick={() => setFilter('offset', String(Math.max(0, offset - limit)))}
            >
              Previous
            </Button>
            <span className="text-sm text-slate-500">
              {offset + 1}–{Math.min(offset + limit, data?.total ?? 0)} of{' '}
              {data?.total?.toLocaleString()}
            </span>
            <Button
              variant="secondary"
              disabled={offset + limit >= (data?.total ?? 0)}
              onClick={() => setFilter('offset', String(offset + limit))}
            >
              Next
            </Button>
          </div>
        )}
      </Card>
    </div>
  )
}
