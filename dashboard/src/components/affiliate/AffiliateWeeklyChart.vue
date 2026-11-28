<script setup lang="ts">
import { dayjs } from 'frappe-ui'
import { LineChart } from 'frappe-ui/charts'
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { __ } from '@/lib/translate'
import type { AffiliatePerformance } from '@/types/affiliates'

interface AffiliateWeeklyChartProps {
	weekly: AffiliatePerformance['weekly']
}

const props = defineProps<AffiliateWeeklyChartProps>()

const rows = computed(() =>
	props.weekly.map((week) => ({
		...week,
		label: dayjs(week.week).format('D MMM'),
	})),
)

const seriesConfig = {
	signups: { label: __('Signups') },
	paying: { label: __('Paying') },
}
</script>

<template>
	<BillingCard
		:title="__('Signups and paying customers by week')"
		:description="
			__(
				'A team pays its first invoice some weeks after it signs up, so recent weeks show fewer paying customers.',
			)
		"
	>
		<div class="h-72 min-w-0">
			<LineChart
				:data="rows"
				x="label"
				:y="['signups', 'paying']"
				:series-config="seriesConfig"
				:x-axis="{ type: 'category' }"
			/>
		</div>
	</BillingCard>
</template>
