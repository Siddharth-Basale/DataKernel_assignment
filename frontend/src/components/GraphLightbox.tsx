import { Maximize2, X } from 'lucide-react'
import { useEffect } from 'react'

export function GraphLightbox({
  open,
  title,
  src,
  onClose,
}: {
  open: boolean
  title: string
  src: string
  onClose: () => void
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="relative flex max-h-[95vh] w-full max-w-6xl flex-col rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <p className="text-lg font-semibold text-slate-900">{title}</p>
            <p className="text-sm text-slate-500">LangGraph workflow — click outside or Esc to close</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="overflow-auto p-4">
          <img
            src={src}
            alt={title}
            className="mx-auto h-auto w-full max-h-[80vh] object-contain"
          />
        </div>
      </div>
    </div>
  )
}

export function GraphThumbnail({
  src,
  alt,
  onOpen,
}: {
  src: string
  alt: string
  onOpen: () => void
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative min-h-[240px] w-full flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white p-2 text-left transition hover:border-brand-400 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-brand-500"
    >
      <img
        src={src}
        alt={alt}
        className="mx-auto h-auto max-h-[360px] w-full object-contain transition group-hover:scale-[1.02]"
      />
      <span className="absolute bottom-3 right-3 flex items-center gap-1 rounded-full bg-white/95 px-2.5 py-1 text-xs font-medium text-brand-700 shadow-sm opacity-0 transition group-hover:opacity-100">
        <Maximize2 className="h-3.5 w-3.5" />
        Expand graph
      </span>
    </button>
  )
}
