<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { LineChart } from 'frappe-ui/charts'
import { computed } from 'vue'
import type { AffiliateRetention } from '@/types/affiliates'

interface AffiliateRetentionCardProps {
	retention: AffiliateRetention
}

const props = defineProps<AffiliateRetentionCardProps>()

const share = (count: number): number =>
	Math.round((count / props.retention.customers) * 100)

const summary = computed(() => {
	const { customers, active_30_days, active_90_days } = props.retention
	return [
		{ label: 'paid customers', value: customers },
		{
			label: `active in 30 days (${share(active_30_days)}%)`,
			value: active_30_days,
		},
		{
			label: `active in 90 days (${share(active_90_days)}%)`,
			value: active_90_days,
		},
	]
})

// A text label keeps each month on its own category; a bare number reads as a position.
const curve = computed(() =>
	props.retention.curve.map((point) => ({
		...point,
		label: `Month ${point.month}`,
	})),
)

const seriesConfig = {
	percent: { label: 'Still paying', color: 'var(--ink-green-5)' },
}
const tooltipColumns = [
	{ name: 'still_paying', label: 'Customers still paying' },
	{ name: 'customers', label: 'Customers this far in' },
]
const yAxis = { min: 0, max: 100, format: (value: number) => `${value}%` }
</script>

<template>
	<section
		class="flex flex-col gap-4 rounded-6 border border-outline-gray-1 bg-surface-base p-5"
	>
		<div class="flex items-start justify-between gap-3">
			<div class="flex flex-col gap-1">
				<h2 class="text-base-semibold text-ink-gray-8">Retention</h2>
				<p class="text-p-sm text-ink-gray-5">
					Among the customers you referred, the share still paying each month
					after their first payment.
				</p>
			</div>
			<Badge theme="gray" label="All time" />
		</div>

		<p v-if="!retention.customers" class="text-p-sm text-ink-gray-5">
			No paying customers yet. When people you referred pay, this shows how long
			they keep paying.
		</p>
		<template v-else>
			<dl class="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-base">
				<div
					v-for="item in summary"
					:key="item.label"
					class="flex items-baseline gap-1.5"
				>
					<dt class="order-2 text-ink-gray-5">{{ item.label }}</dt>
					<dd class="text-base-semibold tabular-nums text-ink-gray-8">
						{{ item.value }}
					</dd>
				</div>
			</dl>

			<p v-if="!retention.curve.length" class="text-p-sm text-ink-gray-5">
				The curve starts once your first customers have paid for a full month.
			</p>
			<div v-else class="h-72">
				<LineChart
					:data="curve"
					x="label"
					y="percent"
					:series-config="seriesConfig"
					:tooltip-columns="tooltipColumns"
					:x-axis="{ type: 'category' }"
					:y-axis="yAxis"
				/>
			</div>
		</template>
	</section>
</template>
