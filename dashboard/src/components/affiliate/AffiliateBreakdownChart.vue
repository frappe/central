<script setup lang="ts">
import { BarChart } from 'frappe-ui/charts'
import BillingCard from '@/components/billing/BillingCard.vue'
import { __ } from '@/lib/translate'
import type { AffiliateCounts } from '@/types/affiliates'

interface AffiliateBreakdownChartProps {
	title: string
	/** The row field that names each bar, such as `source`. */
	labelKey: string
	rows: AffiliateCounts[]
}

defineProps<AffiliateBreakdownChartProps>()

const seriesConfig = {
	signups: { label: __('Signups') },
	paying: { label: __('Paying') },
}
</script>

<template>
	<BillingCard :title="title">
		<div class="h-72 min-w-0">
			<BarChart
				:data="rows"
				:x="labelKey"
				:y="['signups', 'paying']"
				:series-config="seriesConfig"
				:x-axis="{ type: 'category' }"
			/>
		</div>
	</BillingCard>
</template>
