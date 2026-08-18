<script setup lang="ts">
import { Button } from 'frappe-ui'
import { BarChart } from 'frappe-ui/charts'
import { computed, ref } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useInstantChartResize } from '@/composables/useInstantChartResize'
import { money } from '@/lib/format'
import type { SpendHistory } from '@/types/billing'

// Month-by-month spend. A tray is scoped to one cycle; this is the thing that
// genuinely isn't — so it lives here rather than behind a card on Overview.
//
const props = defineProps<{ history: SpendHistory; exportUrl: string }>()

const months = computed(() => props.history.months)

const formatMoney = (value: number): string =>
	money(value, props.history.currency, { trimTrailingZeros: true })

const plotEl = ref<HTMLElement | null>(null)
const chartRef = ref<InstanceType<typeof BarChart> | null>(null)
useInstantChartResize(plotEl, chartRef)
</script>

<template>
	<BillingCard title="Monthly spend">
		<template #action>
			<Button variant="ghost" size="xs" :link="exportUrl" label="Export">
				<template #prefix>
					<span class="lucide-download size-3.5" aria-hidden="true" />
				</template>
			</Button>
		</template>

		<div ref="plotEl" class="h-60">
			<BarChart
				ref="chartRef"
				:data="months"
				x="month"
				y="total"
				:series-config="{ total: { label: 'Spend' } }"
				:y-axis="{ format: formatMoney }"
			/>
		</div>
	</BillingCard>
</template>
