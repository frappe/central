<script setup lang="ts">
import { Button, FormControl, Skeleton } from 'frappe-ui'
import { computed, ref } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAffiliate } from '@/composables/useAffiliate'
import { useAffiliatePerformance } from '@/composables/useAffiliatePerformance'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { AffiliatePeriod } from '@/types/affiliates'
import AffiliateBreakdownChart from './AffiliateBreakdownChart.vue'
import AffiliateCampaignsCard from './AffiliateCampaignsCard.vue'
import AffiliateFunnelCard from './AffiliateFunnelCard.vue'
import AffiliateKpis from './AffiliateKpis.vue'
import AffiliateWeeklyChart from './AffiliateWeeklyChart.vue'

const emit = defineEmits<{ makeLink: [] }>()

// The backend reads an empty product as every product, and frappe-cloud as no product.
const period = ref<AffiliatePeriod>('90d')
const product = ref('')

const { products, sourceLabel } = useAffiliate()
const { performance, loading, error, reload } = useAffiliatePerformance(
	period,
	product,
)

const sourceRows = computed(() =>
	(performance.value?.by_source ?? []).map((row) => ({
		...row,
		source: sourceLabel(row.source),
	})),
)

const periodOptions = [
	{ label: __('Last 30 days'), value: '30d' },
	{ label: __('Last 90 days'), value: '90d' },
	{ label: __('Last 12 months'), value: '12m' },
	{ label: __('All time'), value: 'all' },
]

const productOptions = computed(() => [
	{ label: __('All products'), value: '' },
	{ label: __('Frappe Cloud'), value: 'frappe-cloud' },
	...products.value.map((item) => ({ label: item.title, value: item.name })),
])
</script>

<template>
	<div class="space-y-5">
		<div class="grid max-w-lg grid-cols-2 gap-4">
			<FormControl
				v-model="period"
				type="select"
				:label="__('Period')"
				:options="periodOptions"
			/>
			<FormControl
				v-model="product"
				type="select"
				:label="__('Product')"
				:options="productOptions"
			/>
		</div>

		<EmptyState
			v-if="error && !performance"
			icon="lucide-cloud-off"
			:title="__('Your numbers couldn\'t load')"
			:description="getErrorMessage(error, __('Try again in a moment.'))"
		>
			<template #action>
				<Button :label="__('Retry')" @click="reload" />
			</template>
		</EmptyState>

		<div v-else-if="!performance" class="space-y-4" aria-busy="true">
			<Skeleton class="h-28 rounded-6" />
			<Skeleton class="h-56 rounded-6" />
			<Skeleton class="h-80 rounded-6" />
		</div>

		<EmptyState
			v-else-if="!performance.totals.signups"
			icon="lucide-megaphone"
			:title="__('No signups yet')"
			:description="__('Share your link. Signups from it show here.')"
		>
			<template #action>
				<Button :label="__('Make a link')" @click="emit('makeLink')" />
			</template>
		</EmptyState>

		<div
			v-else
			class="space-y-5 transition-opacity"
			:class="{ 'opacity-60': loading }"
			:aria-busy="loading"
		>
			<AffiliateKpis :totals="performance.totals" />
			<AffiliateFunnelCard :funnel="performance.funnel" />
			<AffiliateWeeklyChart :weekly="performance.weekly" />
			<div class="grid gap-5 lg:grid-cols-2">
				<AffiliateBreakdownChart
					:title="__('By source')"
					label-key="source"
					:rows="sourceRows"
				/>
				<AffiliateBreakdownChart
					:title="__('By product')"
					label-key="product"
					:rows="performance.by_product"
				/>
			</div>
			<AffiliateCampaignsCard :campaigns="performance.campaigns" />
		</div>
	</div>
</template>
