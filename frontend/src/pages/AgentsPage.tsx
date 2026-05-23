import { AgentGraphCard, type AgentCardConfig } from '@/components/AgentGraphCard'
import { Card, CardContent } from '@/components/ui/Card'

const AGENTS: AgentCardConfig[] = [
  {
    id: 1,
    title: 'Agent 1 — Ticket resolution',
    when: 'Every new ticket after draft review (POST /tickets/submit)',
    desc: 'Priority scoring · incident check · RAG reply · auto-resolve or escalate',
    graph: '/agent1_graph.png',
    href: '/tickets/new',
    linkLabel: 'Submit a ticket →',
    trigger: 'Branches: escalate_direct · auto_resolve_direct · retrieve_similar → generate_reply',
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
  {
    id: 5,
    title: 'Agent 5 — Multilingual routing',
    when: 'Non-English tickets (hi, ta, te, bn, …) after ingest or on demand',
    desc: 'Translate message → re-classify in English → localized reply in customer language',
    graph: '/agent5_graph.png',
    href: '/multilingual',
    linkLabel: 'Language gap & batch process →',
    trigger: 'Closes the 18% satisfaction gap for regional-language customers',
  },
]

export function AgentsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Agent control center</h1>
        <p className="text-slate-500">
          Five LangGraph agents — ticket flow, anomalies, retention, leadership reports, and
          multilingual support
        </p>
      </div>

      <Card className="border-brand-200 bg-brand-50/40">
        <CardContent className="space-y-3 py-5 text-sm text-slate-700">
          <p>
            <strong>Cross-agent flow:</strong> Agent 2 flags SKUs → Agent 1 escalates matching
            tickets. Agent 3 builds the retention queue. Agent 4 reads incidents + churn for the
            weekly report. Agent 5 runs when <code className="rounded bg-white px-1">language ≠ en</code>{' '}
            so replies match the customer&apos;s language.
          </p>
          <p className="text-slate-600">
            Tap any graph thumbnail to open a full-size view. Agent 1 graph reflects the updated
            branch: check_incident → calculate_priority → escalate / auto-resolve / RAG reply path.
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
