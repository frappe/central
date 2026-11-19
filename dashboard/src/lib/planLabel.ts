import { money } from '@/lib/format'
import { formatMemory, formatVcpu } from '@/lib/units'

/** Format the plan name or custom CPU and memory size with its billed price. */
export function formatPlanLabel(options: {
	title?: string | null
	rate?: number | null
	currency?: string | null
	billingCycle?: string | null
	vcpus?: number | null
	memoryMegabytes?: number | null
}): string {
	const title = (options.title || '').split(' · ')[0].trim()
	const vcpus = options.vcpus ?? 0
	const memory = options.memoryMegabytes ?? 0
	const tier =
		title ||
		(vcpus > 0 && memory > 0
			? `${formatVcpu(vcpus)} vCPU × ${formatMemory(memory)} RAM`
			: 'Custom configuration')
	if (options.rate == null) return tier
	const cycle = options.billingCycle === 'Annual' ? 'yr' : 'mo'
	const price = money(options.rate, options.currency || 'INR', {
		trimTrailingZeros: true,
	})
	return `${tier} · ${price}/${cycle}`
}
