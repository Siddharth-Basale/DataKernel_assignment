import { useMutation } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { draftTicket, submitTicket } from '@/api'
import { AgentResultPanel } from '@/components/AgentResultPanel'
import { DraftFieldsPanel } from '@/components/DraftFieldsPanel'
import { RagExampleCard } from '@/components/RagExampleCard'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { scoreRagExamples } from '@/lib/rag'
import type { Ticket, TicketDraftRequest } from '@/types'

const PRESETS: { label: string; data: TicketDraftRequest }[] = [
  {
    label: 'Escalation: Samsung S24',
    data: {
      message:
        'My Samsung S24 order shows delivered but I never received it. This is urgent.',
      customer_tier: 'prime_plus',
      product_sku: 'SAMSUNG-S24',
      order_value: 89999,
      customer_name: 'Aarav Sharma',
      customer_id: '0e96b788-ed3c-4cdd-864d-d96afb0858b9',
      channel: 'chat',
      customer_country: 'IN',
      language: 'en',
      product_category: 'Electronics',
      order_id: 'AMZ-S24DEMO-1',
      order_date: '2025-01-14',
    },
  },
  {
    label: 'RAG: Wrong item',
    data: {
      message:
        'I received the wrong item in my sealed package. I ordered WOW shampoo but got something else entirely.',
      customer_tier: 'regular',
      product_sku: 'WOW-SHAMPOO-300ML',
      order_value: 1556.26,
      customer_name: 'Neha Verma',
      channel: 'web',
      customer_country: 'IN',
      language: 'en',
      product_category: 'Beauty & Health',
    },
  },
  {
    label: 'Auto-resolve: Login',
    data: {
      message: 'I cannot login to my account because OTP is not working.',
      customer_tier: 'regular',
      product_sku: 'ACCOUNT-LOGIN',
      order_value: 0,
      customer_name: 'Rahul Mehta',
      channel: 'app',
      customer_country: 'IN',
      language: 'en',
      product_category: 'Account',
    },
  },
]

const emptyForm: TicketDraftRequest = {
  message: '',
  customer_tier: 'regular',
  product_sku: '',
  order_value: 0,
  customer_name: 'Customer',
  channel: 'web',
  customer_country: 'IN',
  language: 'en',
  product_category: 'General',
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-200 p-2 text-sm'

export function NewTicketPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [showMore, setShowMore] = useState(false)
  const [form, setForm] = useState<TicketDraftRequest>(emptyForm)
  const [draft, setDraft] = useState<Ticket | null>(null)
  const [submitPayload, setSubmitPayload] = useState<Record<string, unknown> | null>(null)
  const [result, setResult] = useState<Awaited<ReturnType<typeof submitTicket>> | null>(null)

  const draftMut = useMutation({
    mutationFn: () => draftTicket(form),
    onSuccess: (res) => {
      setDraft(res.draft)
      setSubmitPayload(res.submit_payload)
      setStep(2)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const submitMut = useMutation({
    mutationFn: () => submitTicket(submitPayload ?? {}),
    onSuccess: (res) => {
      setResult(res)
      setStep(3)
      toast.success('Ticket submitted — Agent 1 finished')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const updateDraft = (key: keyof Ticket, value: string | number) => {
    if (!draft) return
    const next = { ...draft, [key]: value }
    setDraft(next)
    setSubmitPayload((p) => ({ ...p, [key]: value }))
  }

  const ragExamples = useMemo(
    () => scoreRagExamples(draft?.rag_examples ?? []),
    [draft?.rag_examples],
  )

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <Link to="/tickets" className="text-sm text-brand-600 hover:underline">
          ← Tickets
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">New ticket</h1>
        <p className="text-slate-500">Draft → review → submit with Agent 1</p>
      </div>

      <div className="flex gap-2">
        {[1, 2, 3].map((s) => (
          <div
            key={s}
            className={`flex-1 rounded-lg py-2 text-center text-sm font-medium ${
              step === s
                ? 'bg-brand-600 text-white'
                : step > s
                  ? 'bg-brand-100 text-brand-800'
                  : 'bg-slate-100 text-slate-500'
            }`}
          >
            {s === 1 ? 'Intake' : s === 2 ? 'Review' : 'Agent 1'}
          </div>
        ))}
      </div>

      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Demo presets</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <Button
                key={p.label}
                variant="secondary"
                onClick={() => {
                  setForm(p.data)
                  setShowMore(true)
                }}
              >
                {p.label}
              </Button>
            ))}
          </CardContent>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="text-sm text-slate-600">Message *</span>
              <textarea
                className={`${inputClass} min-h-[100px]`}
                rows={4}
                value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-sm text-slate-600">Customer tier *</span>
              <select
                className={inputClass}
                value={form.customer_tier}
                onChange={(e) => setForm({ ...form, customer_tier: e.target.value })}
              >
                <option value="regular">regular</option>
                <option value="prime">prime</option>
                <option value="prime_plus">prime_plus</option>
              </select>
            </label>
            <label className="block">
              <span className="text-sm text-slate-600">Product SKU *</span>
              <input
                className={inputClass}
                value={form.product_sku}
                onChange={(e) => setForm({ ...form, product_sku: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-sm text-slate-600">Order value (₹) *</span>
              <input
                type="number"
                className={inputClass}
                value={form.order_value}
                onChange={(e) => setForm({ ...form, order_value: Number(e.target.value) })}
              />
            </label>
            <label className="block">
              <span className="text-sm text-slate-600">Customer name</span>
              <input
                className={inputClass}
                value={form.customer_name ?? ''}
                onChange={(e) => setForm({ ...form, customer_name: e.target.value })}
              />
            </label>
          </CardContent>

          <CardContent className="border-t border-slate-100 pt-0">
            <button
              type="button"
              className="text-sm font-medium text-brand-600 hover:underline"
              onClick={() => setShowMore((v) => !v)}
            >
              {showMore ? 'Hide' : 'Show'} optional fields (channel, order ID, customer ID…)
            </button>
            {showMore && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="block sm:col-span-2">
                  <span className="text-sm text-slate-600">Customer ID</span>
                  <input
                    className={inputClass}
                    value={form.customer_id ?? ''}
                    onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
                    placeholder="UUID for repeat-contact detection"
                  />
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">Channel</span>
                  <select
                    className={inputClass}
                    value={form.channel ?? 'web'}
                    onChange={(e) => setForm({ ...form, channel: e.target.value })}
                  >
                    <option value="web">web</option>
                    <option value="chat">chat</option>
                    <option value="email">email</option>
                    <option value="app">app</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">Product category</span>
                  <input
                    className={inputClass}
                    value={form.product_category ?? ''}
                    onChange={(e) => setForm({ ...form, product_category: e.target.value })}
                  />
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">Country</span>
                  <input
                    className={inputClass}
                    value={form.customer_country ?? 'IN'}
                    onChange={(e) => setForm({ ...form, customer_country: e.target.value })}
                  />
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">Language</span>
                  <input
                    className={inputClass}
                    value={form.language ?? 'en'}
                    onChange={(e) => setForm({ ...form, language: e.target.value })}
                  />
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">Order ID</span>
                  <input
                    className={inputClass}
                    value={form.order_id ?? ''}
                    onChange={(e) => setForm({ ...form, order_id: e.target.value })}
                  />
                </label>
                <label className="block">
                  <span className="text-sm text-slate-600">Order date</span>
                  <input
                    type="date"
                    className={inputClass}
                    value={form.order_date ?? ''}
                    onChange={(e) => setForm({ ...form, order_date: e.target.value })}
                  />
                </label>
              </div>
            )}
          </CardContent>

          <CardContent>
            <Button
              onClick={() => draftMut.mutate()}
              disabled={!form.message || !form.product_sku || draftMut.isPending}
            >
              {draftMut.isPending ? 'Generating draft…' : 'Generate AI draft'}
            </Button>
          </CardContent>
        </Card>
      )}

      {step === 2 && draft && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Customer message</CardTitle>
            </CardHeader>
            <CardContent className="whitespace-pre-wrap text-sm text-slate-700">{draft.message}</CardContent>
          </Card>

          <DraftFieldsPanel draft={draft} editable onUpdate={updateDraft} />

          {ragExamples.length > 0 && (
            <div>
              <h3 className="mb-1 font-medium">RAG examples</h3>
              <p className="mb-3 text-sm text-slate-500">
                Similar resolved tickets used to classify this complaint. Click a card to see the full
                retrieved context.
              </p>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {ragExamples.map((ex, i) => (
                  <RagExampleCard key={i} example={ex} index={i} />
                ))}
              </div>
            </div>
          )}

          <details className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs">
            <summary className="cursor-pointer font-medium text-slate-700">
              Submit payload (debug)
            </summary>
            <pre className="mt-2 max-h-64 overflow-auto">{JSON.stringify(submitPayload, null, 2)}</pre>
          </details>

          <div className="flex gap-3">
            <Button variant="secondary" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button onClick={() => submitMut.mutate()} disabled={submitMut.isPending}>
              {submitMut.isPending ? 'Submitting…' : 'Submit & run Agent 1'}
            </Button>
          </div>
        </div>
      )}

      {step === 3 && result && (
        <div className="space-y-4">
          <AgentResultPanel
            decision={result.agent_state.decision}
            reason={result.agent_state.reason}
            steps={result.agent_state.agent_steps}
            suggestedReply={
              result.stored_ticket.suggested_reply ?? result.agent_state.suggested_reply
            }
            resolutionStatus={result.stored_ticket.resolution_status}
            title="Agent 1 finished"
          />
          <Button onClick={() => navigate(`/tickets/${result.ticket_id}`)}>
            Open ticket {result.ticket_id}
          </Button>
        </div>
      )}
    </div>
  )
}
