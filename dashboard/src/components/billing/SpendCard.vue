<script setup lang="ts">
import { Button, LoadingText, TabButtons } from 'frappe-ui'
import { BarChart, useChartTokens } from 'frappe-ui/charts'
import { computed, ref } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import {
	BILLING_REPORT_MONTHS,
	type useBillingReports,
} from '@/composables/useBillingReports'
import { useSpendingLimits } from '@/composables/useSpendingLimits'
import { currencySymbol, money } from '@/lib/format'
import type { SpendSlice } from '@/types/billing'

interface Props {
	reports: ReturnType<typeof useBillingReports>
}

const props = defineProps<Props>()
const { forecast } = useBillingOverview()
const { current: tierCurrent } = useSpendingLimits()

const MONTH_OPTIONS = BILLING_REPORT_MONTHS.map((option) => ({
	...option,
	label: `${option.value}M`,
}))
const DISPLAY_LABEL: Record<string, string> = { 'VM Plans': 'Servers' }

const months = computed({
	get: () => props.reports.months.value,
	set: (value: number) => {
		props.reports.months.value = value
	},
})

const history = computed(() => props.reports.history.data)
const currency = computed(() => props.reports.currency.value)

const compactFormat = new Intl.NumberFormat('en', {
	notation: 'compact',
	maximumFractionDigits: 1,
})

const compact = (value: number): string =>
	`${currencySymbol(currency.value)}${compactFormat.format(value).toLowerCase()}`

const stats = computed(() => [
	{ label: 'Invoiced', value: history.value?.total ?? 0 },
	{ label: 'Monthly average', value: props.reports.average.value },
	{
		label: 'Paid by credits',
		value: props.reports.statement.data?.settled_by_credits ?? 0,
	},
	{ label: 'Tax', value: props.reports.tax.data?.total_tax ?? 0 },
])

const limit = computed(() => Number(tierCurrent.value?.max_spend ?? 0))

const chartRows = computed(() => {
	const rows = history.value?.months ?? []

	const accrued = Number(
		forecast.data?.measured ?? forecast.data?.projected_total ?? 0,
	)

	return rows.map((row, index) => {
		const isCurrent = index === rows.length - 1
		const current = isCurrent ? Math.max(row.total, accrued) : 0
		const within = limit.value ? Math.min(current, limit.value) : current

		return {
			month: row.month.endsWith('-01') ? row.month.slice(0, 4) : row.label,
			invoiced: isCurrent ? 0 : row.total,
			current: within,
			over: current - within,
			limit: limit.value,
		}
	})
})

const showLimit = computed(
	() =>
		limit.value > 0 &&
		limit.value <=
			Math.max(
				...chartRows.value.map((row) => row.invoiced + row.current + row.over),
			),
)

const hasOverage = computed(() => chartRows.value.some((row) => row.over > 0))

const seriesKeys = computed(() => [
	'invoiced',
	'current',
	...(hasOverage.value ? ['over'] : []),
	...(showLimit.value ? ['limit'] : []),
])

const { tokens } = useChartTokens(ref())

const themeColor = (name: string): string => {
	void tokens.value

	return getComputedStyle(document.documentElement)
		.getPropertyValue(`--${name}`)
		.trim()
}

const seriesConfig = computed(() => ({
	invoiced: { label: 'Invoiced', color: themeColor('surface-gray-7') },
	current: { label: 'This cycle', color: themeColor('surface-gray-4') },
	over: { label: 'Over limit', color: themeColor('surface-amber-6') },
	limit: {
		label: `Spend limit ${money(limit.value, currency.value, { trimTrailingZeros: true })}`,
		type: 'line' as const,
		dashed: true,
		echartOptions: { lineStyle: { width: 1 } },
		color: themeColor('ink-gray-5'),
	},
}))

const MAX_SLICES = 4
const SLICE_SHADES = [7, 5, 4, 3]

const toSlices = (
	rows: SpendSlice[],
	labelFor: (label: string) => string = (label) => label,
) => {
	void tokens.value

	const total = rows.reduce((sum, row) => sum + row.amount, 0)

	if (total <= 0) return { total, slices: [] }

	const sorted = [...rows].sort((a, b) => b.amount - a.amount)
	const kept =
		sorted.length > MAX_SLICES ? sorted.slice(0, MAX_SLICES - 1) : sorted
	const rest = sorted.slice(kept.length)
	const shown = rest.length
		? [
				...kept.map((row) => ({ ...row, label: labelFor(row.label) })),
				{
					label: 'Other',
					amount: rest.reduce((sum, row) => sum + row.amount, 0),
				},
			]
		: kept.map((row) => ({ ...row, label: labelFor(row.label) }))

	return {
		total,
		slices: shown.map((row, index) => ({
			label: row.label,
			amount: row.amount,
			percent: (row.amount / total) * 100,
			color: themeColor(
				`surface-gray-${SLICE_SHADES[index % SLICE_SHADES.length]}`,
			),
		})),
	}
}

const hasSpend = computed(
	() =>
		!props.reports.loading.value &&
		!!history.value &&
		!props.reports.neverBilled.value,
)

const breakdowns = computed(() =>
	[
		{
			title: 'By product',
			...toSlices(
				history.value?.by_product ?? [],
				(label) => DISPLAY_LABEL[label] ?? label,
			),
		},
		{
			title: 'By region',
			...toSlices(history.value?.by_region ?? []),
		},
	].filter((breakdown) => breakdown.slices.length),
)
</script>

<template>
	<div class="grid gap-3 md:gap-4 lg:grid-cols-3">
		<BillingCard title="Spend" class="lg:col-span-2">
			<template #action>
				<div class="flex items-center gap-2">
					<TabButtons v-model="months" size="sm" :options="MONTH_OPTIONS" />
					<!-- A period with no invoices exports an empty file. -->
					<Button
						v-if="(history?.invoice_count ?? 0) > 0"
						size="xs"
						icon="lucide-download"
						label="Export CSV"
						:href="reports.exportUrl('spend')"
					/>
				</div>
			</template>

			<LoadingText v-if="reports.loading.value" :lines="6" />

			<div
				v-else-if="!history"
				class="flex items-center justify-between gap-3 rounded-5 px-4 py-3"
			>
				<p class="text-p-sm text-ink-gray-6">Couldn't load your spend.</p>
				<Button label="Retry" @click="reports.reload()" />
			</div>

			<p
				v-else-if="reports.neverBilled.value"
				class="rounded-5 px-4 py-3 text-p-sm text-ink-gray-6"
			>
				Your spend, payments and tax show up here after your first invoice.
			</p>

			<template v-else>
				<div
					class="-mx-4 grid grid-cols-2 gap-x-4 gap-y-1 border-y border-outline-gray-1 px-4 py-3.5 sm:grid-flow-col sm:grid-cols-4 sm:grid-rows-2"
				>
					<template v-for="stat in stats" :key="stat.label">
						<span class="text-sm text-ink-gray-5">{{ stat.label }}</span>

						<span
							class="text-lg-semibold"
							:class="stat.value ? 'text-ink-gray-9' : 'text-ink-gray-5'"
						>
							{{ money(stat.value, currency) }}
						</span>
					</template>
				</div>

				<div class="mt-4 min-h-64 min-w-0 flex-1">
					<BarChart
						:data="chartRows"
						x="month"
						:y="seriesKeys"
						stacked
						:series-config="seriesConfig"
						:y-axis="{ format: compact }"
					/>
				</div>
			</template>
		</BillingCard>

		<div class="flex flex-col gap-3 md:gap-4">
			<BillingCard v-if="hasSpend" title="Breakdown">
				<template #action>
					<RouterLink
						:to="{ name: 'BillingInvoices' }"
						class="inline-flex items-center gap-1 text-sm text-ink-gray-5 transition-colors hover:text-ink-gray-8"
					>
						View invoices
						<span class="lucide-arrow-right size-3.5" aria-hidden="true" />
					</RouterLink>
				</template>

				<div class="flex flex-col gap-3">
					<div
						v-for="breakdown in breakdowns"
						:key="breakdown.title"
						class="flex flex-col gap-2"
					>
						<h3 class="text-sm-medium text-ink-gray-6">
							{{ breakdown.title }}
						</h3>

						<div class="flex h-1.5 gap-0.5 overflow-hidden rounded-1">
							<span
								v-for="slice in breakdown.slices"
								:key="slice.label"
								:style="{
									width: `${slice.percent}%`,
									backgroundColor: slice.color,
								}"
							/>
						</div>

						<ul class="flex flex-col">
							<li
								v-for="slice in breakdown.slices"
								:key="slice.label"
								class="flex items-center gap-2.5 border-b border-outline-gray-1 py-2 text-base text-ink-gray-8 first:pt-0 last:border-b-0"
							>
								<span
									class="size-2 shrink-0 rounded-1"
									:style="{ backgroundColor: slice.color }"
									aria-hidden="true"
								/>
								<span class="min-w-0 flex-1 truncate">{{ slice.label }}</span>
								<span
									class="w-9 text-right text-sm tabular-nums text-ink-gray-5"
								>
									{{ Math.round(slice.percent) }}%
								</span>
								<span class="tabular-nums">
									{{ money(slice.amount, currency) }}
								</span>
							</li>
						</ul>
					</div>

					<p v-if="!breakdowns.length" class="text-p-sm text-ink-gray-5">
						No itemised charges in this period.
					</p>
				</div>
			</BillingCard>

			<slot />
		</div>
	</div>
</template>
