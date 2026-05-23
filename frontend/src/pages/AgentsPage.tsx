import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Link } from 'react-router-dom'

const AGENTS = [
  {
    id: 1,
    title: 'Agent 1 — Ticket resolution',
    desc: 'Suggest reply · auto-resolve · escalate',
    graph: '/agent1_graph.png',
    href: '/tickets/new',
    linkLabel: 'Submit a ticket →',
  },
  {
    id: 2,
    title: 'Agent 2 — Anomaly investigation',
    desc: 'Z-score spikes · incident reports · SKU flags',
    graph: '/agent2_graph.png',
    href: '/incidents',
    linkLabel: 'Run & view incidents →',
  },
  {
    id: 3,
    title: 'Agent 3 — Customer risk',
    desc: 'Churn score · CLV · drafted retention offers',
    graph: '/agent3_graph.png',
    href: '/retention',
    linkLabel: 'Retention queue →',
  },
] as const

export function AgentsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Agent control center</h1>
        <p className="text-slate-500">
          Three LangGraph agents coordinate through SQLite — no human orchestration
        </p>
      </div>

      <Card className="border-brand-200 bg-brand-50/40">
        <CardContent className="py-5 text-sm text-slate-700">
          <strong>Cross-agent flow:</strong> Agent 2 writes incidents and flags SKUs in the database.
          When you submit a new ticket for a flagged SKU (e.g. SAMSUNG-S24), Agent 1 reads{' '}
          <code className="rounded bg-white px-1">check_active_incidents</code> and auto-escalates.
          Agent 3 runs independently to build the retention queue.
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        {AGENTS.map((agent) => (
          <Card key={agent.id} className="flex flex-col overflow-hidden">
            <CardHeader>
              <CardTitle className="text-base">{agent.title}</CardTitle>
              <p className="text-sm text-slate-500">{agent.desc}</p>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col gap-4">
              <div className="min-h-[280px] flex-1 overflow-auto rounded-lg border border-slate-200 bg-white p-2">
                <img
                  src={agent.graph}
                  alt={`${agent.title} LangGraph`}
                  className="mx-auto h-auto max-h-[420px] w-full object-contain"
                />
              </div>
              <Link to={agent.href} className="text-sm font-medium text-brand-600 hover:underline">
                {agent.linkLabel}
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
