<script setup lang="ts">
import { LineChart } from 'frappe-ui/charts'
import { computed } from 'vue'
import {
	LOAD_SERIES,
	type LoadPoint,
	peakLoad,
	toLoadChartRows,
} from '@/lib/loadChart'

const props = defineProps<{
	points: LoadPoint[]
	/** False when the metrics read itself failed, not when the series is short. */
	available?: boolean
}>()

const peak = computed(() => peakLoad(props.points))
const hasSeries = computed(() => props.points.length > 1)
const rows = computed(() => toLoadChartRows(props.points))
const seriesNames = LOAD_SERIES.map((series) => series.label)
const seriesConfig = Object.fromEntries(
	LOAD_SERIES.map((series) => [series.label, { color: series.color }]),
)
</script>

<template>
	<section class="rounded-7 border border-outline-gray-2 p-5">
		<div class="mb-3 flex items-baseline justify-between gap-3">
			<h3 class="text-base font-semibold text-ink-gray-9">Load average</h3>

			<span v-if="peak > 0" class="text-sm tabular-nums text-ink-gray-5">
				peak {{ peak.toFixed(2) }}
			</span>
		</div>

		<div v-if="hasSeries" class="h-72">
			<LineChart
				:data="rows"
				x="time"
				:y="seriesNames"
				:x-axis="{ type: 'time', timeGrain: 'hour' }"
				:y-axis="{ min: 0 }"
				:series-config="seriesConfig"
			/>
		</div>
		<p
			v-else
			class="grid h-44 place-items-center text-center text-sm text-ink-gray-5"
		>
			{{ available
					? 'Monitoring has not collected enough history yet.'
					: 'Live metrics are unavailable for this server right now.' }}
		</p>
	</section>
</template>
