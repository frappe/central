import { money } from '@/lib/format'

/** Overview Plan row: "Starter · ₹1,500/mo" — tier only, never the title's vCPU echo. */
export function formatPlanLabel(options: {
	title?: string | null
	rate?: number | null
	currency?: string | null
	billingCycle?: string | null
}): string {
	const tier =
		(options.title || '').split(' · ')[0].trim() || 'Custom configuration'
	if (options.rate == null) return tier
	const cycle = options.billingCycle === 'Annual' ? 'yr' : 'mo'
	const price = money(options.rate, options.currency || 'INR', {
		trimTrailingZeros: true,
	})
	return `${tier} · ${price}/${cycle}`
}
