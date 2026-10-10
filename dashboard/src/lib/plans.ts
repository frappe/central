// Display + mapping helpers for billing-catalog plans in the New Server flow.
// Plans come from central.billing.api.dashboard.catalog.get_eligible_plans
// (see usePlans); these turn one into display labels.

import { money } from '@/lib/format'
import {
	formatGb,
	formatMemory,
	formatVcpu,
	gigabytesToMegabytes,
} from '@/lib/units'
import type { Plan } from '@/types/api'

/** A plan's CPU and memory, e.g. "0.125 vCPU · 512 MB RAM". */
export function planSize(plan: Plan): string {
	const vcpus = formatVcpu(planQuantity(plan, 'Compute'))
	const memory = formatMemory(
		gigabytesToMegabytes(planQuantity(plan, 'Memory')),
	)

	return `${vcpus} vCPU · ${memory} RAM`
}

/** The rest of a plan's bundle, e.g. "10 GB disk · 100 GB transfer". */
export function planAllowances(
	plan: Plan,
	options?: { disk?: boolean },
): string {
	return plan.includes
		.filter(
			(inc) =>
				inc.quantity &&
				inc.resource_type in ALLOWANCE_NOUNS &&
				(options?.disk !== false || inc.resource_type !== 'Disk'),
		)
		.map(
			(inc) =>
				`${formatGb(inc.quantity)} ${inc.unit} ${ALLOWANCE_NOUNS[inc.resource_type]}`,
		)
		.join(' · ')
}

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

const ALLOWANCE_NOUNS: Record<string, string> = {
	Disk: 'disk',
	Transfer: 'transfer',
}
