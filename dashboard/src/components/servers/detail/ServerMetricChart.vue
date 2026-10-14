<script setup lang="ts">
import { Button } from 'frappe-ui'
import { AreaChart, ChartCard, useChartTokens } from 'frappe-ui/charts'
import { computed, ref } from 'vue'
import {
	getChartSeriesSummaries,
	getChartSummary,
	type MetricChart,
} from '@/lib/serverMetrics'

interface ServerMetricChartProps {
	chart: MetricChart
	timeGrain: 'minute' | 'hour' | 'day'
}

const props = defineProps<ServerMetricChartProps>()
const hiddenSeries = ref<string[]>([])
const { tokens } = useChartTokens(ref())
const summaries = computed(() => getChartSeriesSummaries(props.chart))
const seriesConfig = computed(() =>
	Object.fromEntries(
		props.chart.series.map((name, index) => [
			name,
			{
				color: tokens.value.categorical[props.chart.colors[index] - 1],
				smooth: false,
				showDataPoints: false,
				fillOpacity: 0.1,
				lineType: index === 0 ? 'solid' : 'dashed',
			},
		]),
	),
)

function toggleSeries(name: string): void {
	if (hiddenSeries.value.includes(name)) {
		hiddenSeries.value = hiddenSeries.value.filter((series) => series !== name)
	} else if (hiddenSeries.value.length < props.chart.series.length - 1) {
		hiddenSeries.value = [...hiddenSeries.value, name]
	}
}

const grid = {
	show: true,
	lineStyle: { type: 'solid', color: 'var(--chart-gridline)' },
}
</script>

<template>
	<ChartCard
		:card="false"
		role="group"
		:aria-label="chart.title"
		class="server-metric-chart flex flex-col gap-3 rounded-6 border border-outline-gray-2 p-3"
	>
		<header class="flex flex-wrap items-start justify-between gap-2">
			<h3 class="text-base-medium text-ink-gray-8">{{ chart.title }}</h3>
			<dl
				v-if="chart.series.length > 1"
				class="grid min-w-64 flex-1 grid-cols-2 gap-x-4 gap-y-3"
			>
				<div
					v-for="summary in summaries"
					:key="summary.name"
					class="min-w-0 space-y-1"
				>
					<dt>
						<Button
							variant="ghost"
							size="sm"
							class="-ms-1 !justify-start !px-1"
							:aria-pressed="!hiddenSeries.includes(summary.name)"
							:aria-label="`${hiddenSeries.includes(summary.name) ? 'Show' : 'Hide'} ${summary.name}`"
							:disabled="!hiddenSeries.includes(summary.name) && hiddenSeries.length === chart.series.length - 1"
							@click="toggleSeries(summary.name)"
						>
							<span
								class="flex items-center gap-1.5 text-sm-medium text-ink-gray-6"
							>
								<span
									v-if="hiddenSeries.includes(summary.name)"
									class="lucide-eye-off size-3 shrink-0"
									aria-hidden="true"
								/>
								<span
									v-else
									class="h-0 w-3 shrink-0 border-t-2"
									:class="seriesConfig[summary.name].lineType === 'dashed' ? 'border-dashed' : 'border-solid'"
									:style="{ borderColor: seriesConfig[summary.name].color }"
									aria-hidden="true"
								/>
								{{ summary.name }}
							</span>
						</Button>
					</dt>
					<dd
						class="flex flex-wrap items-baseline gap-x-2 gap-y-1 tabular-nums"
					>
						<span class="text-lg-medium text-ink-gray-8">
							<span class="sr-only">Current rate: </span
							><bdi dir="ltr">{{ summary.current }}</bdi>
						</span>
						<span v-if="summary.hasSamples" class="text-sm text-ink-gray-5">
							<bdi>Peak {{ summary.peak }}</bdi>
						</span>
					</dd>
				</div>
			</dl>
			<p v-else class="text-sm text-ink-gray-5">{{ getChartSummary(chart) }}</p>
		</header>
		<div class="server-metric-plot h-44 min-w-0">
			<AreaChart
				v-model:hidden-series="hiddenSeries"
				:echart-options="{ animation: false }"
				:data="chart.rows"
				x="time"
				:y="chart.series"
				:series-config="seriesConfig"
				:x-axis="{
					type: 'time',
					timeGrain,
					echartOptions: { splitLine: { show: false } },
				}"
				:y-axis="{
					min: 0,
					max: chart.max,
					format: chart.formatValue ?? chart.format,
					echartOptions: {
						interval: chart.interval ?? (chart.max ? chart.max / 4 : undefined),
						splitNumber: 4,
						splitLine: grid,
						axisLabel: { formatter: chart.format },
					},
				}"
			/>
		</div>
	</ChartCard>
</template>

<style scoped>
/* Reserve space for the header and usage cards while keeping plots readable. */
@media (min-width: 1024px) {
	.server-metric-plot {
		height: clamp(7rem, calc((100dvh - 34rem) / 2), 11rem);
	}
}

/* The summary labels own the series controls, so the plot needs no second legend. */
.server-metric-chart :deep([data-slot="chart-legend"]) {
	display: none;
}
</style>
