<script setup lang="ts">
import { NumberCard } from 'frappe-ui/charts'
import { computed } from 'vue'
import { sampleEarningsPerClick } from '@/composables/useAffiliate'
import type { AffiliateSummary } from '@/types/affiliates'

interface AffiliateKpiCardsProps {
	summary: AffiliateSummary
}

const props = defineProps<AffiliateKpiCardsProps>()

const COMPARED = 'vs previous period'

/** The change from the previous period in percent, or null when there is nothing to compare. */
function change(current: number, previous: number): number | null {
	return previous ? Math.round(((current - previous) / previous) * 100) : null
}

const cards = computed(() => {
	const { totals, previous_totals: previous } = props.summary
	const earnings = sampleEarningsPerClick(totals)
	const clickToPaid = totals.visited
		? (totals.converted / totals.visited) * 100
		: 0

	return [
		{
			title: 'Clicks',
			value: totals.visited,
			delta: change(totals.visited, previous.visited),
		},
		{
			title: 'Signups',
			value: totals.signed_up,
			delta: change(totals.signed_up, previous.signed_up),
		},
		{
			title: 'Paying customers',
			value: totals.converted,
			delta: change(totals.converted, previous.converted),
		},
		{
			title: 'Click → paid',
			value: clickToPaid,
			format: (value: number) => `${value.toFixed(1)}%`,
			caption: `${totals.converted} of ${totals.visited.toLocaleString()} clicks`,
		},
		{
			title: 'Earnings per click',
			value: earnings,
			format: (value: number) => `$${value.toFixed(2)}`,
			delta: change(earnings, sampleEarningsPerClick(previous)),
		},
	]
})
</script>

<template>
	<div class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
		<NumberCard
			v-for="card in cards"
			:key="card.title"
			:title="card.title"
			:value="card.value"
			color="var(--ink-gray-7)"
			:format="card.format"
			:delta="card.delta"
			delta-suffix="%"
			:delta-caption="card.caption ?? (card.delta === null ? undefined : COMPARED)"
		/>
	</div>
</template>
