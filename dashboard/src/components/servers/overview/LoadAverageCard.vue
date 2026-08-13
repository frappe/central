<script setup lang="ts">
import { AxisChart } from 'frappe-ui/experimental'
import { computed } from 'vue'
import {
	LOAD_SERIES,
	type LoadPoint,
	peakLoad,
	toLoadChartRows,
} from '@/lib/loadChart'

const props = defineProps<{
	points: LoadPoint[]
}>()

const peak = computed(() => peakLoad(props.points))
const hasSeries = computed(() => props.points.length > 1)

const chartConfig = computed(() => ({
	data: toLoadChartRows(props.points),
	title: '',
	colors: LOAD_SERIES.map((series) => series.color),
	xAxis: {
		key: 'time',
		type: 'time' as const,
		timeGrain: 'hour' as const,
	},
	yAxis: {
		yMin: 0,
	},
	series: LOAD_SERIES.map((series) => ({
		name: series.label,
		type: 'line' as const,
		color: series.color,
		lineWidth: 2,
		showDataPoints: false,
	})),
	echartOptions: {
		grid: {
			top: 8,
			left: 0,
			right: 4,
			bottom: 28,
			containLabel: true,
		},
		legend: {
			bottom: 0,
			icon: 'circle',
			itemWidth: 8,
			itemHeight: 8,
		},
	},
}))
</script>

<template>
	<section class="rounded-7 border border-outline-gray-2 p-5">
		<div class="mb-4 flex items-baseline justify-between gap-3">
			<h3 class="text-base font-semibold text-ink-gray-9">Load average</h3>

			<span v-if="peak > 0" class="text-sm tabular-nums text-ink-gray-5">
				peak {{ peak.toFixed(2) }}
			</span>
		</div>

		<div v-if="hasSeries" class="load-chart h-44">
			<AxisChart :config="chartConfig" />
		</div>
		<p v-else class="grid h-44 place-items-center text-sm text-ink-gray-5">
			Monitoring has not collected enough history yet.
		</p>
	</section>
</template>

<style scoped>
/* AxisChart's ECharts shell defaults to min-h-[300px]; keep the card compact. */
.load-chart :deep([dir="ltr"]) {
	height: 100%;
	min-height: 0;
	min-width: 0;
	padding: 0;
}
</style>
