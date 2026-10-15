<script setup lang="ts">
import { Button } from 'frappe-ui'
import { AreaChart, ChartCard, useChartTokens } from 'frappe-ui/charts'
import { computed, ref } from 'vue'
import { getChartSeriesSummaries, type MetricChart } from '@/lib/serverMetrics'

interface ServerMetricChartProps {
	chart: MetricChart
	timeGrain: 'minute' | 'hour' | 'day'
}

const props = defineProps<ServerMetricChartProps>()
const hiddenSeries = ref<string[]>([])
// Reads leave the disk; writes enter it.
const seriesIcons: Record<string, string> = {
	Received: 'lucide-arrow-down-left',
	Sent: 'lucide-arrow-up-right',
	Read: 'lucide-hard-drive-upload',
	Write: 'lucide-hard-drive-download',
}
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
		class="server-metric-chart flex min-h-0 flex-col gap-2 rounded-6 border border-outline-gray-2 p-3"
	>
		<header class="flex shrink-0 flex-wrap items-start justify-between gap-3">
			<h3
				class="shrink-0 text-base-medium text-ink-gray-8"
				:class="{ 'mt-0.5': chart.series.length > 1 }"
			>
				{{ chart.title }}
			</h3>
			<dl
				class="ms-auto grid min-w-0 gap-x-4 gap-y-2"
				:class="chart.series.length > 1 ? 'grid-cols-2' : 'grid-cols-1'"
			>
				<div
					v-for="summary in summaries"
					:key="summary.name"
					class="min-w-0"
					:class="{ 'grid grid-cols-[1.5rem_max-content] items-center gap-x-1': chart.series.length > 1 }"
				>
					<dt :class="{ 'sr-only': chart.series.length === 1 }">
						<Button
							v-if="chart.series.length > 1"
							variant="ghost"
							size="sm"
							class="server-series-toggle !size-6 !p-1"
							:tooltip="summary.name"
							:icon="hiddenSeries.includes(summary.name) ? 'lucide-eye-off' : seriesIcons[summary.name]"
							:style="{ '--series-color': seriesConfig[summary.name].color }"
							:aria-pressed="!hiddenSeries.includes(summary.name)"
							:aria-label="`${hiddenSeries.includes(summary.name) ? 'Show' : 'Hide'} ${summary.name}`"
							:disabled="!hiddenSeries.includes(summary.name) && hiddenSeries.length === chart.series.length - 1"
							@click="toggleSeries(summary.name)"
						/>

						<span v-else>Current value</span>
					</dt>
					<dd
						class="tabular-nums"
						:class="chart.series.length > 1 ? 'contents' : 'flex flex-wrap items-baseline justify-end gap-x-2 gap-y-1'"
					>
						<bdi
							dir="ltr"
							class="whitespace-nowrap text-base-medium text-ink-gray-8"
							:class="chart.series.length > 1 ? 'justify-self-start' : 'justify-self-end'"
							>{{ summary.current }}</bdi
						>
						<span
							v-if="summary.hasSamples"
							class="whitespace-nowrap text-xs text-ink-gray-5"
							:class="chart.series.length > 1 ? 'col-start-2 justify-self-start' : 'justify-self-end'"
							><bdi>Peak {{ summary.peak }}</bdi></span
						>
					</dd>
				</div>
			</dl>
		</header>
		<div class="h-44 min-w-0 lg:h-auto lg:min-h-0 lg:flex-1">
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
						axisLabel: { formatter: chart.format, hideOverlap: true },
					},
				}"
			/>
		</div>
	</ChartCard>
</template>

<style scoped>
.server-metric-chart :deep(.server-series-toggle) {
	color: color-mix(in srgb, var(--series-color) 70%, var(--ink-gray-9));
}

/* The summary labels own the series controls, so the plot needs no second legend. */
.server-metric-chart :deep([data-slot="chart-legend"]) {
	display: none;
}
</style>
