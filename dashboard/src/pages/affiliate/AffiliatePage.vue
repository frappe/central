<script setup lang="ts">
import dayjs from 'dayjs'
import { Alert, DateRangePicker, LoadingText } from 'frappe-ui'
import AffiliateBreakdownCard from '@/components/affiliate/AffiliateBreakdownCard.vue'
import AffiliateCountriesCard from '@/components/affiliate/AffiliateCountriesCard.vue'
import AffiliateEarningsCard from '@/components/affiliate/AffiliateEarningsCard.vue'
import AffiliateFunnelCard from '@/components/affiliate/AffiliateFunnelCard.vue'
import AffiliateKpiCards from '@/components/affiliate/AffiliateKpiCards.vue'
import AffiliateLinkCard from '@/components/affiliate/AffiliateLinkCard.vue'
import AffiliateLinksCard from '@/components/affiliate/AffiliateLinksCard.vue'
import AffiliatePerformanceChart from '@/components/affiliate/AffiliatePerformanceChart.vue'
import AffiliateRetentionCard from '@/components/affiliate/AffiliateRetentionCard.vue'
import AffiliateStatusCard from '@/components/affiliate/AffiliateStatusCard.vue'
import Scrollbar from '@/components/common/Scrollbar.vue'
import {
	AFFILIATE_DATE_PRESETS,
	useAffiliate,
} from '@/composables/useAffiliate'

const today = dayjs().format('YYYY-MM-DD')

const {
	account,
	summary,
	retention,
	dateRange,
	applying,
	applyError,
	apply,
	createLink,
	totals,
	linkRows,
	bySource,
	byProduct,
	byCountry,
	products,
} = useAffiliate()
</script>

<template>
	<Teleport defer to="#header-actions">
		<DateRangePicker
			v-if="account.data?.status === 'Active'"
			v-model="dateRange"
			class="w-64"
			format="D MMM YYYY"
			:max="today"
			aria-label="Period"
		>
			<template #prefix>
				<span class="lucide-calendar size-4 text-ink-gray-4" />
			</template>
			<template #actions="{ setRange, close }">
				<button
					v-for="preset in AFFILIATE_DATE_PRESETS"
					:key="preset.label"
					type="button"
					class="w-full rounded-4 px-2 py-1.5 text-left text-base text-ink-gray-7 hover:bg-surface-gray-2"
					@click="() => { setRange(preset.range()); close() }"
				>
					{{ preset.label }}
				</button>
			</template>
		</DateRangePicker>
	</Teleport>

	<Scrollbar class="h-full">
		<div
			class="grid auto-rows-max grid-cols-[min(72rem,100%)] content-start justify-center gap-4 px-3 pb-24 pt-3 md:gap-5 md:px-6 md:pt-7"
		>
			<LoadingText v-if="!account.isFinished" :lines="4" />
			<Alert
				v-else-if="account.error"
				theme="red"
				title="Couldn't load your affiliate account"
				:primary-action="{ label: 'Retry', onClick: () => account.reload() }"
			/>
			<AffiliateStatusCard
				v-else-if="account.data?.status !== 'Active'"
				:status="account.data?.status ?? null"
				:rejection-reason="account.data?.rejection_reason ?? null"
				:applying="applying"
				:apply-error="applyError"
				@apply="apply"
			/>
			<template v-else>
				<LoadingText v-if="!summary.data && !summary.error" :lines="4" />
				<Alert
					v-else-if="summary.error"
					theme="red"
					title="Couldn't load your numbers"
					:primary-action="{ label: 'Retry', onClick: () => summary.reload() }"
				/>
				<AffiliateKpiCards v-else-if="summary.data" :summary="summary.data" />
				<div class="grid gap-4 md:gap-5 lg:grid-cols-[24rem_minmax(0,1fr)]">
					<AffiliateLinkCard
						:code="account.data.affiliate_code ?? ''"
						:products="products"
						:create="createLink"
					/>
					<AffiliatePerformanceChart
						v-if="summary.data"
						:daily="summary.data.daily"
					/>
					<LoadingText v-else-if="!summary.error" :lines="6" />
				</div>
				<template v-if="summary.data">
					<AffiliateFunnelCard :totals="totals" />
					<AffiliateEarningsCard
						:by-product="byProduct"
						:campaigns="linkRows"
						:products="products"
					/>
					<AffiliateCountriesCard :rows="byCountry" />
					<div class="grid gap-4 md:gap-5 lg:grid-cols-2">
						<AffiliateLinksCard :links="linkRows" />
						<AffiliateBreakdownCard
							:views="[
								{ label: 'Source', rows: bySource },
								{ label: 'Product', rows: byProduct },
							]"
						/>
					</div>

					<LoadingText v-if="!retention.data && !retention.error" :lines="4" />
					<Alert
						v-else-if="retention.error"
						theme="red"
						title="Couldn't load retention"
						:primary-action="{
							label: 'Retry',
							onClick: () => retention.reload(),
						}"
					/>
					<AffiliateRetentionCard
						v-else-if="retention.data"
						:retention="retention.data"
					/>
				</template>
			</template>
		</div>
	</Scrollbar>
</template>
