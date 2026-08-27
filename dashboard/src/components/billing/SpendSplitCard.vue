<script setup lang="ts">
import { TabButtons } from 'frappe-ui'
import { DonutChart } from 'frappe-ui/charts'
import { computed, ref } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { money } from '@/lib/format'
import type { SpendHistory, SpendSlice } from '@/types/billing'

const props = defineProps<{ history: SpendHistory }>()
const axis = ref<'product' | 'region'>('product')

const DISPLAY_LABEL: Record<string, string> = { 'VM Plans': 'Server plans' }

const source = computed<SpendSlice[]>(() =>
	(axis.value === 'product'
		? props.history.by_product
		: props.history.by_region
	).map((row) => ({ ...row, label: DISPLAY_LABEL[row.label] ?? row.label })),
)

const formatMoney = (value: number): string =>
	money(value, props.history.currency)

const cardTitle = computed(() =>
	axis.value === 'product' ? 'Spend by product' : 'Spend by region',
)
</script>

<template>
	<BillingCard :title="cardTitle">
		<template #action>
			<TabButtons
				v-model="axis"
				:options="[
					{ label: 'Product', value: 'product' },
					{ label: 'Region', value: 'region' },
				]"
			/>
		</template>

		<div class="h-full min-h-64">
			<DonutChart
				:data="source"
				category="label"
				value="amount"
				:max-slices="5"
				center-label="itemised"
				:format="formatMoney"
			>
				<template #empty>No itemised charges in this period.</template>
			</DonutChart>
		</div>
	</BillingCard>
</template>
