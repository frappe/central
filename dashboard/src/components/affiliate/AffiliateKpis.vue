<script setup lang="ts">
import { computed } from 'vue'
import { __ } from '@/lib/translate'
import type { AffiliateTotals } from '@/types/affiliates'

interface AffiliateKpisProps {
	totals: AffiliateTotals
}

const props = defineProps<AffiliateKpisProps>()

const share = (part: number, whole: number): number =>
	whole ? Math.round((part / whole) * 100) : 0

/** Percent change from the period before, or null when there is nothing to compare. */
const change = (current: number, previous: number | null): number | null =>
	previous ? Math.round(((current - previous) / previous) * 100) : null

const cells = computed(() => {
	const totals = props.totals
	return [
		{
			label: __('Signups'),
			value: String(totals.signups),
			change: change(totals.signups, totals.previous_signups),
			note: null,
		},
		{
			label: __('Paying customers'),
			value: String(totals.paying),
			change: change(totals.paying, totals.previous_paying),
			note: null,
		},
		{
			label: __('Signup to paid'),
			value: `${share(totals.paying, totals.signups)}%`,
			change: null,
			note: __('{0} of {1} signups', [totals.paying, totals.signups]),
		},
		{
			label: __('Still paying'),
			value: `${share(totals.still_paying, totals.paying)}%`,
			change: null,
			note: __('{0} paid in the last {1} days', [
				totals.still_paying,
				totals.still_paying_days,
			]),
		},
	]
})
</script>

<template>
	<section
		class="grid grid-cols-2 divide-outline-gray-1 rounded-6 border border-outline-gray-1 bg-surface-base md:grid-cols-4 md:divide-x"
	>
		<div v-for="cell in cells" :key="cell.label" class="px-5 py-4">
			<p class="text-p-sm text-ink-gray-6">{{ cell.label }}</p>
			<p class="mt-2 text-2xl-semibold text-ink-gray-9">{{ cell.value }}</p>
			<p
				v-if="cell.change !== null"
				class="mt-2 flex items-center gap-1 text-p-sm"
				:class="cell.change >= 0 ? 'text-ink-green-6' : 'text-ink-red-6'"
			>
				<span
					:class="[
						cell.change >= 0 ? 'lucide-trending-up' : 'lucide-trending-down',
						'size-3.5',
					]"
					aria-hidden="true"
				/>
				{{ __('{0}% vs previous period', [Math.abs(cell.change)]) }}
			</p>
			<p v-else-if="cell.note" class="mt-2 text-p-sm text-ink-gray-6">
				{{ cell.note }}
			</p>
		</div>
	</section>
</template>
