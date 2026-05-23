import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { GraphLightbox, GraphThumbnail } from '@/components/GraphLightbox'

export type AgentCardConfig = {
  id: number
  title: string
  when: string
  desc: string
  graph: string
  href: string
  linkLabel: string
  trigger?: string
}

export function AgentGraphCard({ agent }: { agent: AgentCardConfig }) {
  const [lightbox, setLightbox] = useState(false)

  return (
    <>
      <Card className="flex flex-col overflow-hidden">
        <CardHeader className="space-y-2">
          <CardTitle className="text-base">{agent.title}</CardTitle>
          <p className="rounded-md bg-slate-50 px-2 py-1.5 text-xs text-slate-600">
            <span className="font-semibold text-slate-700">When: </span>
            {agent.when}
          </p>
          <p className="text-sm text-slate-500">{agent.desc}</p>
          {agent.trigger && (
            <p className="text-xs text-brand-600">{agent.trigger}</p>
          )}
        </CardHeader>
        <CardContent className="flex flex-1 flex-col gap-4">
          <GraphThumbnail
            src={agent.graph}
            alt={`${agent.title} LangGraph`}
            onOpen={() => setLightbox(true)}
          />
          <Link to={agent.href} className="text-sm font-medium text-brand-600 hover:underline">
            {agent.linkLabel}
          </Link>
        </CardContent>
      </Card>
      <GraphLightbox
        open={lightbox}
        title={agent.title}
        src={agent.graph}
        onClose={() => setLightbox(false)}
      />
    </>
  )
}
