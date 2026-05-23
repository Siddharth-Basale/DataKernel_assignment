import { AgentGraphCard, type AgentCardConfig } from '@/components/AgentGraphCard'
import { Card, CardContent } from '@/components/ui/Card'
import { Link } from 'react-router-dom'

const AGENTS: AgentCardConfig[] = [
  {
    id: 1,
    title: 'Agent 1 — Ticket resolution',
    when: 'Every new ticket after draft review (POST /tickets/submit)',
    desc: 'Translate non-English messages · priority · incidents · RAG · localized reply (hi/ta/te/bn)',
    graph: '/agent1_graph.png',
    href: '/tickets/new',
    linkLabel: 'Submit a ticket →',
    trigger:
      'prepare_language → check_incident → calculate_priority → escalate / auto-resolve / RAG → localized save',
  },
  {
    id: 2,
    title: 'Agent 2 — Anomaly investigation',
    when: 'Scheduled or on-demand spike scan (POST /agent2/run)',
    desc: 'Z-score on category volumes · incident reports · SKU flags for Agent 1',
    graph: '/agent2_graph.png',
    href: '/incidents',
    linkLabel: 'Run & view incidents →',
  },
  {
    id: 3,
    title: 'Agent 3 — Customer risk',
    when: 'Nightly or manual churn scan (POST /agent3/run)',
    desc: 'High-contact customers · churn score · CLV · drafted retention offers',
    graph: '/agent3_graph.png',
    href: '/retention',
    linkLabel: 'Retention queue →',
  },
  {
    id: 4,
    title: 'Agent 4 — Weekly insight report',
    when: 'Sunday 06:00 schedule or on-demand (POST /api/agents/weekly-report/run)',
    desc: 'Week-over-week KPIs · leadership narrative · HTML report with Agent 2 + 3 context',
    graph: '/agent4_graph.png',
    href: '/reports',
    linkLabel: 'Generate & view reports →',
  },
]

export function AgentsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Agent control center</h1>
        <p className="text-slate-500">
          Four LangGraph agents — ticket flow (with built-in multilingual), anomalies, retention,
          and leadership reports
        </p>
      </div>

      <Card className="border-brand-200 bg-brand-50/40">
        <CardContent className="space-y-3 py-5 text-sm text-slate-700">
          <p>
            <strong>Cross-agent flow:</strong> Agent 2 flags SKUs → Agent 1 escalates matching
            tickets. Agent 3 builds the retention queue. Agent 4 reads incidents + churn for the
            weekly report.
          </p>
          <p>
            <strong>Multilingual:</strong> When{' '}
            <code className="rounded bg-white px-1">language ≠ en</code>, Agent 1 translates the
            message to English for RAG, then saves a localized reply (e.g. Hindi) plus{' '}
            <code className="rounded bg-white px-1">message_en</code> on the ticket. See{' '}
            <Link to="/multilingual" className="text-brand-600 hover:underline">
              Language coverage
            </Link>{' '}
            for stats and batch re-processing.
          </p>
          <p className="text-slate-600">
            Tap any graph thumbnail to open a full-size view.
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {AGENTS.map((agent) => (
          <AgentGraphCard key={agent.id} agent={agent} />
        ))}
      </div>
    </div>
  )
}
