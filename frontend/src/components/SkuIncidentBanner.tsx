import { AlertTriangle } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { SkuFlag } from '@/types'

export function SkuIncidentBanner({ flag }: { flag: SkuFlag }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
      <div>
        <p className="font-medium text-amber-900">
          Active incident on SKU <code className="font-mono">{flag.product_sku}</code>
        </p>
        <p className="mt-1 text-amber-800">
          Agent 2 flagged this SKU ({flag.severity} · {flag.category}). Agent 1 will auto-escalate
          new tickets for this product.
        </p>
        <Link to="/incidents" className="mt-2 inline-block text-brand-600 hover:underline">
          View incidents →
        </Link>
      </div>
    </div>
  )
}
