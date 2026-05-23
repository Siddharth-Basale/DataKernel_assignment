import type { RagExample } from '@/types'

/**
 * Chroma returns "distance" (lower = closer), not similarity.
 * - Cosine distance: 0 = identical, 2 = opposite → % = (1 - distance) * 100
 * - L2 distance: unbounded → relative rank within the result batch
 */
export function distancesToSimilarityPercent(distances: number[]): number[] {
  if (distances.length === 0) return []
  const allCosineLike = distances.every((d) => d >= 0 && d <= 2)
  if (allCosineLike) {
    return distances.map((d) => Math.max(0, Math.min(100, Math.round((1 - d) * 100))))
  }
  const min = Math.min(...distances)
  const max = Math.max(...distances)
  if (max <= min) return distances.map(() => 100)
  const span = max - min
  return distances.map((d) =>
    Math.max(0, Math.min(100, Math.round(100 * (1 - (d - min) / span)))),
  )
}

export function scoreRagExamples(examples: RagExample[]): (RagExample & {
  message: string
  agent_reply: string
  similarity: number
})[] {
  const distances = examples.map((e) => e.distance).filter((d): d is number => d != null)
  const fallbackScores =
    distances.length === examples.length
      ? distancesToSimilarityPercent(distances)
      : []

  return examples.map((raw, index) => {
    const normalized = normalizeRagExample(raw)
    const fromBackend = raw.similarity_percent
    const fromBatch = fallbackScores[index]
    const similarity =
      fromBackend != null && Number.isFinite(fromBackend)
        ? Math.round(fromBackend)
        : normalized.similarity ?? fromBatch ?? undefined

    return {
      ...normalized,
      similarity: similarity ?? 0,
    }
  })
}

/** Backend returns Chroma hits as { category, sub_category, distance, text }. */
export function normalizeRagExample(raw: RagExample): RagExample & {
  message: string
  agent_reply: string
  similarity?: number
} {
  const text = raw.text ?? ''
  let message = raw.message ?? ''
  let agent_reply = raw.agent_reply ?? ''

  if (text && (!message || !agent_reply)) {
    const msgMatch = text.match(/Customer message:\s*([\s\S]*?)(?:\nAgent reply:|$)/i)
    const replyMatch = text.match(/Agent reply:\s*([\s\S]*)/i)
    if (msgMatch) message = msgMatch[1].trim()
    if (replyMatch) agent_reply = replyMatch[1].trim()
    if (!message && !agent_reply) message = text
  }

  let similarity: number | undefined
  if (raw.similarity_percent != null && Number.isFinite(raw.similarity_percent)) {
    similarity = Math.round(raw.similarity_percent)
  } else if (raw.distance != null && Number.isFinite(raw.distance)) {
    const d = raw.distance
    if (d >= 0 && d <= 2) {
      similarity = Math.max(0, Math.min(100, Math.round((1 - d) * 100)))
    }
    // else: leave undefined; parent should call scoreRagExamples for batch-relative L2
  }

  return {
    ...raw,
    message,
    agent_reply,
    similarity,
  }
}
