<script setup lang="ts">
import { DonutChart } from 'frappe-ui/charts'
import { computed } from 'vue'
import Table from '@/components/common/Table.vue'
import { type LinkRow, sampleEarnings } from '@/composables/useAffiliate'
import type { FunnelRow, LinkProduct } from '@/types/affiliates'

interface AffiliateEarningsCardProps {
	byProduct: FunnelRow[]
	campaigns: LinkRow[]
	products: LinkProduct[]
}

const props = defineProps<AffiliateEarningsCardProps>()

const money = (value: number): string =>
	`$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
const moneyPerClick = (value: number): string => `$${value.toFixed(2)}`

const titles = computed(
	() => new Map(props.products.map(({ name, title }) => [name, title])),
)

// Products earning the most first.
const productRows = computed(() =>
	props.byProduct
		.map((row) => {
			const earnings = sampleEarnings(row.converted)
			return {
				...row,
				name: titles.value.get(row.label) ?? row.label,
				earnings,
				rate: row.signed_up ? (row.converted / row.signed_up) * 100 : 0,
				epc: row.visited ? earnings / row.visited : 0,
			}
		})
		.sort((a, b) => b.earnings - a.earnings || b.visited - a.visited)
		.map((row, index) => ({ ...row, rank: index + 1 })),
)

const columns = [
	{ key: 'rank', label: '#' },
	{ key: 'name', label: 'Product' },
	{ key: 'visited', label: 'Clicks' },
	{ key: 'signed_up', label: 'Signups' },
	{ key: 'converted', label: 'Paying' },
	{ key: 'rate', label: 'Conversion rate' },
	{ key: 'earnings', label: 'Earnings' },
	{ key: 'epc', label: 'EPC' },
]

const campaignSlices = computed(() =>
	props.campaigns
		.map((row) => ({
			campaign: row.slug,
			earnings: sampleEarnings(row.converted),
		}))
		.filter((row) => row.earnings > 0),
)
</script>

<template>
	<div class="grid gap-4 md:gap-5 lg:grid-cols-[minmax(0,1fr)_26rem]">
		<section
			class="flex min-w-0 flex-col gap-3 rounded-6 border border-outline-gray-1 bg-surface-base p-5"
		>
			<h2 class="text-base-semibold text-ink-gray-8">Earnings by product</h2>
			<p v-if="!productRows.length" class="text-p-sm text-ink-gray-5">
				No visits or signups in this period.
			</p>
			<Table v-else :columns="columns" :rows="productRows">
				<template #rate="{ row }">{{ row.rate.toFixed(1) }}%</template>
				<template #earnings="{ row }">{{ money(row.earnings) }}</template>
				<template #epc="{ row }">{{ moneyPerClick(row.epc) }}</template>
			</Table>
		</section>

		<section
			class="flex min-w-0 flex-col gap-3 rounded-6 border border-outline-gray-1 bg-surface-base p-5"
		>
			<h2 class="text-base-semibold text-ink-gray-8">Earnings by campaign</h2>
			<p v-if="!campaignSlices.length" class="text-p-sm text-ink-gray-5">
				No earnings in this period yet.
			</p>
			<div v-else class="min-h-64 flex-1">
				<DonutChart
					:data="campaignSlices"
					category="campaign"
					value="earnings"
					center-label="Total earnings"
					:format="money"
					:max-slices="6"
				/>
			</div>
		</section>
	</div>
</template>
