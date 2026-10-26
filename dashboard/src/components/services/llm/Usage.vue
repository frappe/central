<script setup lang="ts">
import { Button, LoadingText, Select } from 'frappe-ui'
import { AreaChart, BarChart, useChartTokens } from 'frappe-ui/charts'
import { computed, ref, watch } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useAI } from '@/composables/useAI'
import { getErrorMessage } from '@/lib/feedback'
import { compactNumber, usd } from '@/lib/format'

type Metric = 'cost' | 'requests' | 'tokens'

interface Props {
	active: boolean
}

defineProps<Props>()

const { usage, usageLoading, usageError, loadUsage, apiKeys } = useAI()

const periodOptions = [
	{ label: 'Today', value: 'Today' },
	{ label: 'Yesterday', value: 'Yesterday' },
	{ label: 'Last 7 days', value: 'Last 7 Days' },
	{ label: 'Last 30 days', value: 'Last 30 Days' },
	{ label: 'This month', value: 'This Month' },
	{ label: 'Last month', value: 'Last Month' },
]

const period = ref('This Month')

const apiKey = ref('')
const keyOptions = computed(() => [
	{ label: 'All keys', value: '' },
	...apiKeys.value.map((key) => ({
		label: key.status === 'active' ? key.title : `${key.title} (revoked)`,
		value: key.name,
	})),
])

const reload = (): void => {
	loadUsage({ period: period.value, key: apiKey.value })
}

watch([period, apiKey], reload, { immediate: true })

const METRICS: { key: Metric; label: string; format: (n: number) => string }[] =
	[
		{ key: 'cost', label: 'Cost', format: usd },
		{ key: 'requests', label: 'Requests', format: (n) => n.toLocaleString() },
		{ key: 'tokens', label: 'Tokens', format: compactNumber },
	]

const OTHER = 'Other'
const { tokens: chartTokens } = useChartTokens(ref())
const palette = computed(() => chartTokens.value.categorical)
const SHOWN_MODELS = 5

const rows = computed(() => {
	const ranked = [...(usage.value?.models ?? [])].sort(
		(a, b) => b.cost - a.cost,
	)
	const shown =
		ranked.length > SHOWN_MODELS + 1 ? ranked.slice(0, SHOWN_MODELS) : ranked
	const named = shown.map((row, index) => ({
		...row,
		label: row.model.split('/').pop() ?? row.model,
		color: palette.value[index % palette.value.length],
	}))
	const tail = ranked.slice(shown.length)
	if (!tail.length) return named

	const sum = (metric: Metric) =>
		tail.reduce((total, row) => total + row[metric], 0)
	return [
		...named,
		{
			model: OTHER,
			label: `${tail.length} other models`,
			requests: sum('requests'),
			tokens: sum('tokens'),
			cost: sum('cost'),
			color: themeColor('ink-gray-4'),
		},
	]
})

const totals = computed(
	() => usage.value?.totals ?? { requests: 0, tokens: 0, cost: 0 },
)

const share = (value: number, metric: Metric): number =>
	totals.value[metric] ? (value / totals.value[metric]) * 100 : 0

const days = computed(() => {
	const named = new Set(rows.value.map((row) => row.model))
	const byDay = new Map<string, Record<Metric, Record<string, number>>>()

	for (const row of usage.value?.daily ?? []) {
		const day = byDay.get(row.day) ?? { cost: {}, requests: {}, tokens: {} }
		const model = named.has(row.model) ? row.model : OTHER
		for (const { key } of METRICS)
			day[key][model] = (day[key][model] ?? 0) + row[key]
		byDay.set(row.day, day)
	}

	const series = (metric: Metric): Record<string, number | string>[] =>
		[...byDay].map(([day, values]) => ({ day, ...values[metric] }))
	return {
		cost: series('cost'),
		requests: series('requests'),
		tokens: series('tokens'),
	}
})

const themeColor = (name: string): string => {
	void chartTokens.value
	return getComputedStyle(document.documentElement)
		.getPropertyValue(`--${name}`)
		.trim()
}

const seriesConfig = computed(() =>
	Object.fromEntries(
		rows.value.map((row) => [
			row.model,
			{ label: row.label, color: row.color },
		]),
	),
)

const dailyTotals = computed(() =>
	days.value.cost.map(({ day }, index) => {
		const sum = (metric: Metric) =>
			Object.entries(days.value[metric][index])
				.filter(([key]) => key !== 'day' && !hiddenSeries.value.includes(key))
				.reduce((total, [, value]) => total + Number(value), 0)
		return { day, requests: sum('requests'), tokens: sum('tokens') }
	}),
)

const trendConfig = computed(() => {
	const series = (label: string, color: string) => ({
		label,
		color,
		smooth: true,
		echartOptions: {
			lineStyle: { width: 1.5 },
			areaStyle: {
				opacity: 0.3,
				color: {
					type: 'linear',
					x: 0,
					y: 0,
					x2: 0,
					y2: 1,
					colorStops: [
						{ offset: 0, color },
						{ offset: 1, color: themeColor('surface-base') },
					],
				},
			},
		},
	})
	return {
		requests: series('Requests', palette.value[0]),
		tokens: series('Tokens', palette.value[6]),
	}
})

const gridLine = computed(() => ({
	lineStyle: { color: themeColor('outline-gray-2') },
}))

const axisFormat = (metric: Metric) => (value: number) =>
	metric === 'cost' ? `$${compactNumber(value)}` : compactNumber(value)

const hiddenSeries = ref<string[]>([])
const toggle = (model: string): void => {
	hiddenSeries.value = hiddenSeries.value.includes(model)
		? hiddenSeries.value.filter((name) => name !== model)
		: [...hiddenSeries.value, model]
}

watch([period, apiKey], () => (hiddenSeries.value = []))

const isEmpty = computed(() => !usageLoading.value && !rows.value.length)
</script>

<template>
	<div class="flex flex-col gap-4 md:gap-5">
		<Teleport v-if="active" defer to="#ai-tab-controls">
			<div class="flex items-center gap-2">
				<Select
					v-model="apiKey"
					:options="keyOptions"
					align="end"
					aria-label="API key"
				/>
				<Select
					v-model="period"
					:options="periodOptions"
					align="end"
					aria-label="Period"
				/>
			</div>
		</Teleport>

		<div
			v-if="usageError && !usage"
			class="flex items-center justify-between gap-3 rounded-6 border border-outline-gray-1 px-5 py-4"
		>
			<p class="text-p-sm text-ink-gray-6">
				{{ getErrorMessage(usageError, "Couldn't load usage.") }}
			</p>
			<Button label="Retry" @click="reload" />
		</div>

		<LoadingText v-else-if="usageLoading && !usage" :lines="6" />

		<p
			v-else-if="isEmpty"
			class="rounded-6 border border-dashed border-outline-gray-2 px-4 py-12 text-center text-p-sm text-ink-gray-5"
		>
			No requests in this period{{ apiKey ? ' through this key' : '' }}.
		</p>

		<div
			v-else
			class="usage-charts grid gap-4 transition-opacity duration-200 md:grid-cols-2 md:gap-5"
			:class="usageLoading && 'opacity-60'"
		>
			<section
				v-for="metric in METRICS"
				:key="metric.key"
				class="flex flex-col gap-2 rounded-6 border border-outline-gray-2 bg-surface-base px-5 pb-3 pt-4"
				:class="metric.key === 'cost' && 'md:col-span-2'"
			>
				<header class="flex items-baseline justify-between gap-3">
					<h2 class="text-base-semibold text-ink-gray-8">{{ metric.label }}</h2>
					<span
						class="tabular-nums text-ink-gray-9"
						:class="
							metric.key === 'cost' ? 'text-2xl-semibold' : 'text-lg-semibold'
						"
					>
						{{ metric.format(totals[metric.key]) }}
					</span>
				</header>

				<div v-if="metric.key === 'cost'" class="h-64">
					<BarChart
						v-model:hidden-series="hiddenSeries"
						:data="days.cost"
						x="day"
						:y="rows.map((row) => row.model)"
						stacked
						:series-config="seriesConfig"
						:y-axis="{ min: 0, format: axisFormat('cost') }"
						:echart-options="{ yAxis: { splitLine: gridLine } }"
					/>
				</div>
				<div v-else class="h-52">
					<AreaChart
						:data="dailyTotals"
						x="day"
						:y="metric.key"
						:series-config="trendConfig"
						:y-axis="{ min: 0, format: axisFormat(metric.key) }"
						:echart-options="{ yAxis: { splitNumber: 3, splitLine: gridLine } }"
					/>
				</div>
			</section>

			<BillingCard
				title="By model"
				title-info="Select a model to hide it in the charts. Days are in UTC."
				class="border-outline-gray-2 md:col-span-2"
			>
				<table class="w-full border-separate border-spacing-0 text-left">
					<thead>
						<tr class="text-sm text-ink-gray-5">
							<th scope="col" class="pb-2 font-normal">Model</th>
							<th
								scope="col"
								class="hidden w-28 pb-2 text-right font-normal sm:table-cell"
							>
								Requests
							</th>
							<th
								scope="col"
								class="hidden w-28 pb-2 text-right font-normal sm:table-cell"
							>
								Tokens
							</th>
							<th scope="col" class="w-28 pb-2 text-right font-normal">Cost</th>
							<th
								scope="col"
								class="hidden w-40 pb-2 pl-6 font-normal md:table-cell"
							>
								Share of cost
							</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="row in rows"
							:key="row.model"
							class="transition-opacity duration-150"
							:class="hiddenSeries.includes(row.model) && 'opacity-40'"
						>
							<td class="border-t border-outline-gray-1 py-1.5 pr-3">
								<button
									type="button"
									class="-mx-1.5 flex max-w-full items-center gap-2.5 rounded-2 px-1.5 py-1 text-left hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
									:aria-pressed="!hiddenSeries.includes(row.model)"
									:title="`Show or hide ${row.label} in the charts`"
									@click="toggle(row.model)"
								>
									<span
										class="size-2 shrink-0 rounded-full"
										:style="{ backgroundColor: row.color }"
										aria-hidden="true"
									/>
									<span
										class="truncate text-sm text-ink-gray-8"
										:class="row.model !== OTHER && 'font-mono'"
									>
										{{ row.label }}
									</span>
								</button>
							</td>
							<td
								class="hidden border-t border-outline-gray-1 py-1.5 text-right text-sm tabular-nums text-ink-gray-7 sm:table-cell"
							>
								{{ row.requests.toLocaleString() }}
							</td>
							<td
								class="hidden border-t border-outline-gray-1 py-1.5 text-right text-sm tabular-nums text-ink-gray-7 sm:table-cell"
							>
								{{ compactNumber(row.tokens) }}
							</td>
							<td
								class="border-t border-outline-gray-1 py-1.5 text-right text-sm-medium tabular-nums text-ink-gray-9"
							>
								{{ usd(row.cost) }}
							</td>
							<td
								class="hidden border-t border-outline-gray-1 py-1.5 pl-6 md:table-cell"
							>
								<span class="flex items-center gap-2">
									<span
										class="h-1 flex-1 overflow-hidden rounded-full bg-surface-gray-2"
									>
										<span
											class="block h-full rounded-full"
											:style="{
												backgroundColor: row.color,
												width: `${share(row.cost, 'cost')}%`,
											}"
										/>
									</span>
									<span
										class="w-9 text-right text-xs tabular-nums text-ink-gray-5"
									>
										{{ Math.round(share(row.cost, 'cost')) }}%
									</span>
								</span>
							</td>
						</tr>
					</tbody>
				</table>
			</BillingCard>
		</div>
	</div>
</template>

<style scoped>
.usage-charts :deep([data-slot="chart-legend"]) {
	display: none;
}
</style>
