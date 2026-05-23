import { Badge } from '@/components/ui/Badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { formatInr, parseJsonArray } from '@/lib/format'
import type { Ticket } from '@/types'

function Field({ label, value }: { label: string; value?: string | number | boolean | null }) {
  if (value === undefined || value === null || value === '') return null
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-sm font-medium text-slate-800">{String(value)}</p>
    </div>
  )
}

export function DraftFieldsPanel({
  draft,
  editable = false,
  onUpdate,
}: {
  draft: Ticket
  editable?: boolean
  onUpdate?: (key: keyof Ticket, value: string | number) => void
}) {
  const entities = parseJsonArray<string>(draft.key_entities)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Ticket context</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Customer" value={draft.customer_name} />
          <Field label="Tier" value={draft.customer_tier} />
          <Field label="Customer ID" value={draft.customer_id} />
          <Field label="Channel" value={draft.channel} />
          <Field label="Country" value={draft.customer_country} />
          <Field label="Language" value={draft.language} />
          <Field label="Product category" value={draft.product_category} />
          <Field label="Product SKU" value={draft.product_sku} />
          <Field label="Order ID" value={draft.order_id} />
          <Field label="Order date" value={draft.order_date} />
          <Field label="Order value" value={formatInr(draft.order_value)} />
          <Field
            label="Repeat contact"
            value={draft.is_repeat_contact === true || draft.is_repeat_contact === 'true' ? 'Yes' : 'No'}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>AI enrichment</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 text-sm">
          {editable && onUpdate ? (
            <>
              <label>
                Summary
                <textarea
                  className="mt-1 w-full rounded border p-2"
                  rows={2}
                  value={draft.summary ?? ''}
                  onChange={(e) => onUpdate('summary', e.target.value)}
                />
              </label>
              <label>
                Category
                <input
                  className="mt-1 w-full rounded border p-2"
                  value={draft.category ?? ''}
                  onChange={(e) => onUpdate('category', e.target.value)}
                />
              </label>
              <label>
                Sub-category
                <input
                  className="mt-1 w-full rounded border p-2"
                  value={draft.sub_category ?? ''}
                  onChange={(e) => onUpdate('sub_category', e.target.value)}
                />
              </label>
            </>
          ) : (
            <>
              <Field label="Summary" value={draft.summary} />
              <Field label="Category" value={`${draft.category} / ${draft.sub_category}`} />
            </>
          )}
          <div className="flex flex-wrap gap-2">
            <Badge kind="frustration" value={draft.frustration_level} />
            <Badge kind="status" value={draft.resolution_status} />
            <span className="text-slate-600">Sentiment {draft.sentiment_score}</span>
            <span className="text-slate-600">Urgency {draft.urgency_score}</span>
            <span className="text-red-600">At risk {formatInr(draft.revenue_at_risk)}</span>
          </div>
          {entities.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {entities.map((e) => (
                <span key={e} className="rounded-full bg-slate-100 px-2 py-1 text-xs">
                  {e}
                </span>
              ))}
            </div>
          )}
          {draft.suggested_fields_reason && (
            <p className="rounded-lg bg-slate-50 p-3 text-slate-600">{draft.suggested_fields_reason}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
