// Display + mapping helpers for billing-catalog plans in the New Server flow.
// Plans come from central.billing.api.dashboard.catalog.get_eligible_plans
// (see usePlans); these turn one into a spec line, a price label, and the raw
// size create_server still takes — Atlas provisions resources, not plan names.

import { money } from '@/lib/format'
import type { Plan } from '@/types/api'

/** Compact spec line from a plan's bundled resources, e.g. "2 vCPU · 4 GB RAM · 40 GB disk". */
export function planSpecs(plan: Plan, options?: { disk?: boolean }): string {
	const parts = plan.includes
		.filter((inc) => {
			if (!inc.quantity) return false
			if (options?.disk === false)
				return inc.resource_type === 'Compute' || inc.resource_type === 'Memory'
			return inc.resource_type in NOUNS
		})
		.map((inc) =>
			`${formatQty(inc.quantity)} ${inc.unit} ${nounFor(inc.resource_type)}`.trim(),
		)
	return parts.join(' · ') || '—'
}

/** Price label for a plan card, e.g. "₹4,000 / mo" or "$49 / yr". */
export function planPrice(plan: Plan): string {
	const cycle = plan.billing_cycle === 'Annual' ? 'yr' : 'mo'
	return `${money(plan.rate, plan.currency, { trimTrailingZeros: true })} / ${cycle}`
}

export function planQuantity(plan: Plan, resourceType: string): number {
	return (
		plan.includes.find((inc) => inc.resource_type === resourceType)?.quantity ??
		0
	)
}

// The resource types that map to a server's core spec line get a friendly noun;
// the rest (Transfer/IP/Snapshot) just show their own unit.
const NOUNS: Record<string, string> = {
	Compute: '',
	Memory: 'RAM',
	Disk: 'disk',
}

function nounFor(resourceType: string): string {
	return NOUNS[resourceType] ?? ''
}

function formatQty(quantity: number): string {
	return Number.isInteger(quantity) ? `${quantity}` : quantity.toFixed(1)
}
