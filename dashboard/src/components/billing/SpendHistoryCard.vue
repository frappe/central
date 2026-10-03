<script setup lang="ts">
import { Button } from 'frappe-ui'
import { BarChart } from 'frappe-ui/charts'
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { money } from '@/lib/format'
import type { SpendHistory } from '@/types/billing'

const props = defineProps<{ history: SpendHistory; exportUrl: string }>()

const months = computed(() => props.history.months)

const formatMoney = (value: number): string =>
	money(value, props.history.currency, { trimTrailingZeros: true })
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

		<div class="h-60">
			<BarChart
				:data="months"
				x="month"
				y="total"
				:series-config="{ total: { label: 'Spend' } }"
				:y-axis="{ format: formatMoney }"
			/>
		</div>
	</BillingCard>
</template>
