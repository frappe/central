import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import type { TierLevel, TrustTier } from '@/types/billing'

interface Gate {
	label: string
	done: boolean
	ratio: number
	detail: string
}

interface Requirement {
	text: string
	met: boolean
}

type RungState = 'reached' | 'current' | 'locked'

export function useSpendingLimits() {
	const { activeTeam } = useSession()
	const { forecast, credit, methods } = useBillingOverview()
	const tier = useCall<TrustTier, { team: string }>({
		url: method(API.trustTier),
		params: () => ({ team: activeTeam.value! }),
		immediate: false,
		refetch: true,
	})
	whenTeamReady(() => tier.reload())

	const currency = computed(() => tier.data?.currency || 'INR')
	const current = computed(() => tier.data?.current)
	const progress = computed(() => tier.data?.progress)
	const monthlySpend = computed(() => forecast.data?.projected_total)
	const nextLevel = computed(() => tier.data?.next ?? null)

	const payingSince = computed(() => {
		const firstPaidAt = progress.value?.first_paid_at
		if (!firstPaidAt) return null
		const months = Math.max(
			0,
			Math.floor(
				(Date.now() - new Date(firstPaidAt).getTime()) /
					(1000 * 60 * 60 * 24 * 30),
			),
		)
		return months < 1
			? '< 1 month'
			: `${months} month${months === 1 ? '' : 's'}`
	})

	const cycleRatio = computed(() => {
		const cap = Number(current.value?.max_spend ?? 0)
		const spent = Number(monthlySpend.value ?? 0)
		return cap ? Math.min(1, spent / cap) : 0
	})
	const resourcesUsed = computed(() =>
		Number(progress.value?.resources_used ?? 0),
	)
	const resourceRatio = computed(() => {
		const cap = Number(current.value?.max_resource_count ?? 0)
		return cap ? Math.min(1, resourcesUsed.value / cap) : 0
	})
	const record = computed(() =>
		[
			payingSince.value ? `Customer for ${payingSince.value}` : null,
			Number(progress.value?.last_paid_invoice_amount) > 0
				? `Last paid invoice ${money(progress.value!.last_paid_invoice_amount, currency.value, { trimTrailingZeros: true })}`
				: null,
		]
			.filter(Boolean)
			.join(' · '),
	)

	const gates = computed<Gate[]>(() => {
		const level = nextLevel.value
		const values = progress.value
		if (!level || !values) return []

		const result: Gate[] = []
		const addGate = (
			label: string,
			have: number,
			need: number,
			format: (value: number) => string = String,
		) => {
			const done = have >= need
			result.push({
				label,
				done,
				ratio: Math.min(1, need ? have / need : 1),
				detail: `${format(done ? need : have)} of ${format(need)}`,
			})
		}

		if (level.min_paid_invoices)
			addGate(
				'Paid invoices',
				Number(values.paid_invoices ?? 0),
				level.min_paid_invoices,
			)
		if (level.min_cumulative_paid)
			addGate(
				'Paid to date',
				Number(values.cumulative_paid ?? 0),
				Number(level.min_cumulative_paid),
				(value) => money(value, currency.value),
			)
		return result
	})

	function requirementsFor(level: TierLevel): Requirement[] {
		const paid = Number(progress.value?.paid_invoices ?? 0)
		const cumulative = Number(progress.value?.cumulative_paid ?? 0)
		if (level.sequence <= 0) {
			const hasChargeableMethod = (methods.data ?? []).some(
				(method) => method.status === 'Active' && !method.reauth_required,
			)
			return [
				{
					text: 'Payment method added or prepaid credits available',
					met: hasChargeableMethod || Number(credit.data?.balance ?? 0) > 0,
				},
			]
		}

		const requirements: Requirement[] = []
		if (level.min_paid_invoices) {
			const count = level.min_paid_invoices
			requirements.push({
				text: `≥ ${count} paid invoice${count === 1 ? '' : 's'}`,
				met: paid >= count,
			})
		}
		if (level.min_cumulative_paid)
			requirements.push({
				text: `≥ ${money(level.min_cumulative_paid, currency.value)} paid to date`,
				met: cumulative >= Number(level.min_cumulative_paid),
			})
		return requirements.length
			? requirements
			: [{ text: 'No additional requirements', met: true }]
	}

	const levels = computed(() => {
		const all = (tier.data?.all_levels ?? []).filter(
			(level): level is TierLevel => Boolean(level),
		)
		const currentIndex = all.findIndex(
			(level) => level.tier === current.value?.tier,
		)
		return all.map((level, index) => ({
			...level,
			state: (index < currentIndex
				? 'reached'
				: index === currentIndex
					? 'current'
					: 'locked') as RungState,
		}))
	})

	function tierLabel(level: TierLevel | null | undefined): string {
		return level?.tier || '—'
	}
	function reloadAfterMethodAdded(): void {
		tier.reload()
		methods.reload()
	}

	return {
		tier,
		currency,
		current,
		progress,
		monthlySpend,
		nextLevel,
		cycleRatio,
		resourcesUsed,
		resourceRatio,
		record,
		gates,
		levels,
		requirementsFor,
		tierLabel,
		reloadAfterMethodAdded,
		reload: () => tier.reload(),
	}
}
