// Display + mapping helpers for billing-catalog plans in the New Server flow.
// Plans come from central.billing.api.dashboard.catalog.get_eligible_plans
// (see usePlans); these turn one into a spec line, a price label, and the raw
// size create_server still takes — Atlas provisions resources, not plan names.

import type { Plan } from '@/types/api'

/** Compact spec line from a plan's bundled resources, e.g. "2 vCPU · 4 GB RAM · 40 GB disk". */
export function planSpecs(plan: Plan): string {
  const parts = plan.includes
    .filter((inc) => inc.quantity)
    .map((inc) => `${formatQty(inc.quantity)} ${inc.unit} ${nounFor(inc.resource_type)}`.trim())
  return parts.join(' · ') || '—'
}

/** Price label for a plan card, e.g. "₹4,000 / mo" or "$49 / yr". */
export function planPrice(plan: Plan): string {
  const cycle = plan.billing_cycle === 'Annual' ? 'yr' : 'mo'
  return `${formatMoney(plan.rate, plan.currency)} / ${cycle}`
}

/** A plan's bundled resources as the raw size create_server takes (Atlas owns the
 *  catalog of names; we pass concrete vcpus/memory/disk). Memory is stored in
 *  megabytes; sub-1-vCPU bundles also carry a fractional CPU bandwidth cap. */
export function planResources(plan: Plan): {
  vcpus: number
  memory_megabytes: number
  disk_gigabytes: number
  cpu_max_cores?: number
} {
  const qty = (type: string) =>
    plan.includes.find((inc) => inc.resource_type === type)?.quantity ?? 0
  const vcpu = qty('Compute')
  return {
    vcpus: Math.max(1, Math.ceil(vcpu)),
    memory_megabytes: Math.round(qty('Memory') * 1024),
    disk_gigabytes: Math.round(qty('Disk')),
    cpu_max_cores: vcpu > 0 && vcpu < 1 ? vcpu : undefined,
  }
}

// The resource types that map to a server's core spec line get a friendly noun;
// the rest (Transfer/IP/Snapshot) just show their own unit.
const NOUNS: Record<string, string> = { Compute: '', Memory: 'RAM', Disk: 'disk' }

function nounFor(resourceType: string): string {
  return NOUNS[resourceType] ?? ''
}

function formatQty(quantity: number): string {
  return Number.isInteger(quantity) ? `${quantity}` : quantity.toFixed(1)
}

export function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
  }).format(amount)
}
