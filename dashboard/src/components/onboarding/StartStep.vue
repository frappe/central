<script setup lang="ts">
import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import { planPrice } from '@/lib/plans'
import type { ProvisionablePlans } from '@/types/api'

const { credit } = useBillingOverview()

// Without a region the catalog prices the team's plans at their base rate.
const planCatalog = useCall<ProvisionablePlans, { team: string }>({
	url: method(API.eligiblePlans),
	params: teamParams,
	immediate: false,
})
whenTeamReady(() => planCatalog.reload())

const cheapestPlan = computed(() => {
	const plans = Object.values(planCatalog.data?.plans ?? {}).flat()
	return plans.reduce<(typeof plans)[number] | null>(
		(cheapest, plan) =>
			!cheapest || plan.rate < cheapest.rate ? plan : cheapest,
		null,
	)
})

const creditsNote = computed(() => {
	const parts: string[] = []
	const balance = credit.data?.balance ?? 0
	if (balance > 0)
		parts.push(
			`Your team has ${money(balance, credit.data?.currency, { trimTrailingZeros: true })} in credits.`,
		)
	if (cheapestPlan.value)
		parts.push(`Servers start at ${planPrice(cheapestPlan.value)}.`)
	return parts.join(' ')
})

const MAP_GUIDE = [
	{ icon: 'lucide-circle-dot', text: 'Each dot on the map is a region.' },
	{ icon: 'lucide-plus', text: 'A + means you can create a server there.' },
	{
		icon: 'lucide-mouse-pointer-click',
		text: 'Click a server to open it.',
	},
]

defineExpose({
	canSubmit: true,
	submitLabel: 'Go to servers',
	saving: false,
	submit: async () => true,
})
</script>

<template>
	<div class="space-y-4">
		<ul class="space-y-3">
			<li
				v-for="line in MAP_GUIDE"
				:key="line.icon"
				class="flex items-center gap-3 text-p-base text-ink-gray-7"
			>
				<span
					class="grid size-7 shrink-0 place-items-center rounded-6 bg-surface-gray-2"
				>
					<span
						:class="line.icon"
						class="size-4 text-ink-gray-6"
						aria-hidden="true"
					/>
				</span>
				{{ line.text }}
			</li>
		</ul>
		<p
			v-if="creditsNote"
			class="rounded-6 bg-surface-gray-1 p-3 text-p-sm text-ink-gray-6"
		>
			{{ creditsNote }}
		</p>
	</div>
</template>
