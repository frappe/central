import type { Server } from '@/types'

/** Compact spec summary for a server row, e.g. "2 vCPU · 4 GB RAM · 40 GB".
 *  Skips parts the mirror hasn't reported yet. */
export function formatSpecs(server: Server): string {
  const parts: string[] = []
  if (server.vcpus) parts.push(`${server.vcpus} vCPU`)
  if (server.memory_megabytes) parts.push(`${formatMemory(server.memory_megabytes)} RAM`)
  if (server.disk_gigabytes) parts.push(`${server.disk_gigabytes} GB`)
  return parts.join(' · ') || '—'
}

/** MB → human GB/MB. The doctype stores memory in megabytes. */
export function formatMemory(megabytes: number): string {
  if (megabytes >= 1024) {
    const gb = megabytes / 1024
    return `${Number.isInteger(gb) ? gb : gb.toFixed(1)} GB`
  }
  return `${megabytes} MB`
}

/** ISO datetime → short relative-ish label. Returns '' when unset. */
export function formatSyncedAt(value: string | null): string {
  if (!value) return ''
  const date = new Date(value.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
