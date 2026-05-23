import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  getHealth,
  getInsights,
  getInsightsTrends,
  listIncidents,
  listRetentionQueue,
  listTickets,
} from '@/api'
import { ChartBox } from '@/components/ChartBox'
import { KpiCard } from '@/components/KpiCard'
import { Badge } from '@/components/ui/Badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { formatInrCrore } from '@/lib/format'

const PIE_COLORS = ['#2563eb', '#16a34a', '#f59e0b', '#ef4444', '#8b5cf6', '#64748b']

export function DashboardPage() {
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth })
  const { data: insights, isLoading } = useQuery({ queryKey: ['insights'], queryFn: getInsights })
  const { data: trends } = useQuery({
    queryKey: ['insights-trends'],
    queryFn: () => getInsightsTrends('week'),
  })
  const { data: incidents } = useQuery({
    queryKey: ['incidents-preview'],
    queryFn: () => listIncidents(true, 5),
  })
  const { data: retention } = useQuery({
    queryKey: ['retention-preview'],
    queryFn: () => listRetentionQueue(true, 5),
  })
  const { data: recentTickets } = useQuery({
    queryKey: ['recent-tickets'],
    queryFn: () => listTickets({ limit: 8, offset: 0 }),
  })

  if (health?.tickets === 0) {
    return (
      <Card className="mx-auto max-w-lg text-center">
        <CardContent className="space-y-4 py-12">
          <h1 className="text-xl font-semibold">Welcome to Support Insight</h1>
          <p className="text-slate-600">Load the dataset to see leadership metrics and agent demos.</p>
          <Link
            to="/setup"
            className="inline-flex rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Go to setup
          </Link>
        </CardContent>
      </Card>
    )
  }

  const totals = insights?.totals ?? {}
  const trendPoints =
    trends?.points.map((p) => ({
      name: (p.period ?? p.day ?? '').slice(0, 10),
      sentiment: Number(p.avg_sentiment?.toFixed(2)),
      tickets: p.ticket_count,
    })) ?? []

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Executive dashboard</h1>
        <p className="text-slate-500">Top issues, sentiment trends, and revenue at risk</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Total tickets" value={String(totals.ticket_count ?? 0)} />
        <KpiCard
          label="Open risk"
          value={String(totals.unresolved_count ?? 0)}
          sub="pending + unresolved + escalated"
          accent="warning"
        />
        <KpiCard
          label="Revenue at risk"
          value={formatInrCrore(totals.revenue_at_risk)}
          accent="danger"
        />
        <KpiCard
          label="Avg sentiment"
          value={Number(totals.avg_sentiment ?? 0).toFixed(2)}
          sub={`urgency ${Number(totals.avg_urgency ?? 0).toFixed(2)}`}
          accent={Number(totals.avg_sentiment) < -0.5 ? 'danger' : 'neutral'}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Top categories</CardTitle>
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <div className="h-64 animate-pulse rounded bg-slate-100" />
                ) : (
                  <ChartBox height={256}>
                    <BarChart data={insights?.top_categories ?? []} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" />
                      <YAxis dataKey="name" type="category" width={100} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="count" fill="#2563eb" radius={4} />
                    </BarChart>
                  </ChartBox>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Status distribution</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartBox height={256}>
                  <PieChart>
                    <Pie
                      data={insights?.status_distribution ?? []}
                      dataKey="count"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      label={({ name }) => name}
                    >
                      {(insights?.status_distribution ?? []).map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ChartBox>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Top sub-categories</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartBox height={256}>
                  <BarChart data={(insights?.top_sub_categories ?? []).slice(0, 8)}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-25} textAnchor="end" height={60} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" fill="#16a34a" radius={4} />
                  </BarChart>
                </ChartBox>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Languages</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartBox height={256}>
                  <BarChart data={insights?.language_distribution ?? []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" fill="#8b5cf6" radius={4} />
                  </BarChart>
                </ChartBox>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Sentiment trend (weekly)</CardTitle>
            </CardHeader>
            <CardContent>
              <ChartBox height={288}>
                <LineChart data={trendPoints}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                  <YAxis yAxisId="left" domain={[-1, 0.2]} />
                  <YAxis yAxisId="right" orientation="right" />
                  <Tooltip />
                  <Legend />
                  <Line yAxisId="left" type="monotone" dataKey="sentiment" stroke="#2563eb" name="Avg sentiment" />
                  <Line yAxisId="right" type="monotone" dataKey="tickets" stroke="#f59e0b" name="Tickets" />
                </LineChart>
              </ChartBox>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sentiment & revenue by category</CardTitle>
            </CardHeader>
            <CardContent>
              <ChartBox height={280}>
                <BarChart
                  data={(insights?.sentiment_by_category ?? []).slice(0, 7).map((row) => ({
                    name: row.category?.replace(/_/g, ' ') ?? '',
                    tickets: row.tickets,
                    sentiment: Number(row.avg_sentiment?.toFixed(2)),
                    risk: row.revenue_at_risk,
                  }))}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-20} textAnchor="end" height={70} />
                  <YAxis yAxisId="left" />
                  <YAxis yAxisId="right" orientation="right" />
                  <Tooltip />
                  <Legend />
                  <Bar yAxisId="left" dataKey="tickets" fill="#2563eb" name="Tickets" radius={4} />
                  <Bar yAxisId="right" dataKey="risk" fill="#ef4444" name="Revenue at risk" radius={4} />
                </BarChart>
              </ChartBox>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Latest tickets</CardTitle>
              <Link to="/tickets" className="text-sm text-brand-600 hover:underline">
                View all →
              </Link>
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">ID</th>
                    <th className="px-4 py-2 font-medium">Customer</th>
                    <th className="px-4 py-2 font-medium">Issue</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Agent</th>
                  </tr>
                </thead>
                <tbody>
                  {(recentTickets?.items ?? []).map((t) => (
                    <tr key={t.ticket_id} className="border-t border-slate-50 hover:bg-slate-50">
                      <td className="px-4 py-2">
                        <Link
                          to={`/tickets/${t.ticket_id}`}
                          className="font-mono text-brand-600 hover:underline"
                        >
                          {t.ticket_id}
                        </Link>
                      </td>
                      <td className="px-4 py-2">{t.customer_name}</td>
                      <td className="px-4 py-2 capitalize">{t.category?.replace(/_/g, ' ')}</td>
                      <td className="px-4 py-2">
                        <Badge kind="status" value={t.resolution_status} />
                      </td>
                      <td className="px-4 py-2">
                        {t.agent_decision ? (
                          <Badge kind="decision" value={t.agent_decision} />
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Active incidents</CardTitle>
              <Link to="/incidents" className="text-sm text-brand-600 hover:underline">
                View all
              </Link>
            </CardHeader>
            <CardContent className="space-y-3">
              {(incidents?.items ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">Run Agent 2 to detect spikes.</p>
              ) : (
                incidents?.items.map((inc) => (
                  <div key={inc.incident_id} className="rounded-lg border border-slate-100 p-3">
                    <div className="flex items-center gap-2">
                      <Badge kind="severity" value={inc.severity} />
                      <span className="text-sm font-medium">{inc.title}</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{inc.category}</p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Retention queue</CardTitle>
              <Link to="/retention" className="text-sm text-brand-600 hover:underline">
                View all
              </Link>
            </CardHeader>
            <CardContent className="space-y-3">
              {(retention?.items ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">Run Agent 3 to build the queue.</p>
              ) : (
                retention?.items.map((row) => (
                  <div key={row.queue_id} className="rounded-lg border border-slate-100 p-3">
                    <p className="text-sm font-medium">{row.customer_name}</p>
                    <p className="text-xs text-slate-500">
                      Churn {row.churn_score.toFixed(1)} · {row.top_issue}
                    </p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
