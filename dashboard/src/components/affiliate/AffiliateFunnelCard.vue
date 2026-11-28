<script setup lang="ts">
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { __ } from '@/lib/translate'
import type { AffiliateFunnel } from '@/types/affiliates'

interface AffiliateFunnelCardProps {
	funnel: AffiliateFunnel
}

const props = defineProps<AffiliateFunnelCardProps>()

const steps = computed(() => {
	const funnel = props.funnel
	const counts = [
		{ label: __('Signed up'), count: funnel.signed_up },
		{ label: __('Started a site'), count: funnel.started_site },
		{ label: __('Added a card'), count: funnel.added_card },
		{ label: __('Paying'), count: funnel.paying },
	]
	return counts.map((step, index) => {
		const previous = index ? counts[index - 1].count : null
		return {
			...step,
			width: funnel.signed_up ? (step.count / funnel.signed_up) * 100 : 0,
			// Each step after the first shows the share of the step before it.
			share: previous ? Math.round((step.count / previous) * 100) : null,
		}
	})
})
</script>

<template>
	<BillingCard :title="__('Where people stop')">
		<div class="space-y-3">
			<div
				v-for="step in steps"
				:key="step.label"
				class="grid grid-cols-[8rem_1fr_5.5rem] items-center gap-4 sm:grid-cols-[11rem_1fr_6rem]"
			>
				<span class="text-base text-ink-gray-8">{{ step.label }}</span>
				<div class="h-6 overflow-hidden rounded-4 bg-surface-gray-2">
					<div
						class="h-full rounded-4 bg-surface-gray-4"
						:style="{ width: `${step.width}%` }"
					/>
				</div>
				<span class="text-end text-base tabular-nums text-ink-gray-8">
					{{ step.count }}
					<span v-if="step.share !== null" class="ms-1 text-ink-gray-5">
						{{ step.share }}%
					</span>
				</span>
			</div>
		</div>
		<p
			v-if="funnel.waiting_to_pay"
			class="mt-4 flex items-center gap-2 text-p-sm text-ink-gray-6"
		>
			<span class="lucide-hourglass size-3.5" aria-hidden="true" />
			{{ __('{0} added a card and haven\'t paid yet.', [
					funnel.waiting_to_pay,
				]) }}
		</p>
	</BillingCard>
</template>
