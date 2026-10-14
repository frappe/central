<script setup lang="ts">
import { Button, DateTimePicker, dayjs, Select, Skeleton } from 'frappe-ui'
import { computed } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import UsageCard from '@/components/common/UsageCard.vue'
import { usePlans } from '@/composables/usePlans'
import { formatBytes, usagePercent } from '@/lib/bytes'
import { timeAgo } from '@/lib/datetime'
import {
	formatSampleInterval,
	getChartTimeGrain,
	getMetricCharts,
	METRIC_PERIODS,
} from '@/lib/serverMetrics'
import { formatVcpu } from '@/lib/units'
import type {
	MetricsRange,
	ServerMonitoring,
	ServerOverview,
} from '@/types/servers'
import ServerMetricChart from './ServerMetricChart.vue'

interface Props {
	overview: ServerOverview
	metrics: ServerMonitoring | null
	metricsError: string
}

const props = defineProps<Props>()

const range = defineModel<MetricsRange>('range', { required: true })

const emit = defineEmits<{ refresh: [] }>()

const server = computed(() => props.overview.server)
const monitoring = computed(
	() => props.metrics ?? { available: false, points: [] },
)
const points = computed(() => monitoring.value.points ?? [])

const isCustom = computed(() => range.value.period === 'custom')
const period = computed(() =>
	METRIC_PERIODS.find((option) => option.value === range.value.period),
)

const setRange = (change: Partial<MetricsRange>): void => {
	range.value = { ...range.value, ...change }
}

const freshness = computed(() => {
	const interval = monitoring.value.sample_interval_seconds
	const last = points.value[points.value.length - 1]
	if (!interval || !last) return null

	return `Every ${formatSampleInterval(interval)} · Updated ${timeAgo(Math.min(last.time, Date.now() / 1000))}`
})

const SITE_CLOCK = 'YYYY-MM-DD HH:mm:ss'

const choosePeriod = (value: string): void => {
	if (value !== 'custom') {
		setRange({ period: value })
		return
	}

	const now = window.system_timezone
		? dayjs().tz(window.system_timezone)
		: dayjs()

	setRange({
		period: value,
		start: now.startOf('day').format(SITE_CLOCK),
		end: now.format(SITE_CLOCK),
	})
}

const timeGrain = computed(() => getChartTimeGrain(points.value))

const memoryTotal = computed(
	() => (server.value.memory_megabytes ?? 0) * 1024 * 1024,
)

const charts = computed(() =>
	points.value.length > 1
		? getMetricCharts(points.value, memoryTotal.value / 1024 ** 3)
		: [],
)

const { plans } = usePlans(computed(() => server.value.region))

const transferQuota = computed(() => {
	const gigabytes = plans.value
		.find((plan) => plan.plan === server.value.plan)
		?.includes.find((include) => include.resource_type === 'Transfer')?.quantity

	return gigabytes ? gigabytes * 1024 ** 3 : null
})

const transferred = computed(() =>
	points.value.reduce(
		(total, point, index) => {
			const previous = points.value[index - 1] ?? points.value[index + 1]
			const seconds = previous ? Math.abs(point.time - previous.time) : 0

			return {
				received:
					total.received + (point.received_bytes_per_second ?? 0) * seconds,
				sent: total.sent + (point.sent_bytes_per_second ?? 0) * seconds,
			}
		},
		{ received: 0, sent: 0 },
	),
)

const transferredBytes = computed(
	() => transferred.value.received + transferred.value.sent,
)

const usage = computed(() => {
	const now = points.value[points.value.length - 1]
	if (!now) return []

	const memory = Math.min(now.memory_bytes, memoryTotal.value)

	const cpu = Math.round(now.cpu_percent ?? 0)

	return [
		{
			label: 'CPU',
			icon: 'lucide-cpu',
			used: `${cpu}%`,
			limit: server.value.vcpus
				? `${formatVcpu(server.value.vcpus)} vCPU`
				: null,
			percent: cpu,
			badge: null,
		},
		{
			label: 'Memory',
			icon: 'lucide-memory-stick',
			used: formatBytes(memory),
			limit: formatBytes(memoryTotal.value),
			percent: Math.round(usagePercent(memory, memoryTotal.value)),
			badge: null,
		},
		{
			label: 'Disk',
			icon: 'lucide-hard-drive',
			used: formatBytes(now.disk_used_bytes),
			limit: formatBytes(now.disk_total_bytes),
			percent: Math.round(
				usagePercent(now.disk_used_bytes, now.disk_total_bytes),
			),
			badge: null,
		},
		{
			label: isCustom.value ? 'Network' : `Network · ${period.value?.short}`,
			icon: 'lucide-arrow-down-up',
			used: formatBytes(transferredBytes.value),
			limit: transferQuota.value
				? `${formatBytes(transferQuota.value)} / mo`
				: null,
			percent: transferQuota.value
				? Math.round(usagePercent(transferredBytes.value, transferQuota.value))
				: null,
			badge: null,
		},
	]
})
</script>

<template>
	<EmptyState
		v-if="metricsError"
		icon="lucide-cloud-off"
		title="Usage couldn't load"
		:description="metricsError"
	>
		<template #action>
			<Button label="Retry" @click="emit('refresh')" />
		</template>
	</EmptyState>

	<div
		v-else-if="!metrics"
		class="space-y-3 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:gap-3 lg:space-y-0"
		aria-busy="true"
	>
		<div
			class="server-usage-grid grid shrink-0 gap-3 md:grid-cols-2 md:gap-4 lg:grid-cols-4"
		>
			<Skeleton
				v-for="index in 4"
				:key="index"
				class="server-usage-placeholder h-28 rounded-6"
			/>
		</div>

		<div class="flex h-7 shrink-0 items-center">
			<h2 class="text-lg-semibold text-ink-gray-8">Usage</h2>
		</div>

		<div class="grid gap-3 md:grid-cols-2 lg:min-h-0 lg:flex-1 lg:grid-rows-2">
			<Skeleton
				v-for="index in 4"
				:key="index"
				class="h-64 rounded-6 lg:h-auto lg:min-h-0"
			/>
		</div>
	</div>

	<div
		v-else-if="monitoring.available"
		class="space-y-3 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:gap-3 lg:space-y-0"
	>
		<div
			v-if="usage.length"
			class="server-usage-grid grid shrink-0 gap-3 md:grid-cols-2 md:gap-4 lg:grid-cols-4"
		>
			<UsageCard
				v-for="meter in usage"
				:key="meter.label"
				v-bind="meter"
				class="server-usage-card"
			/>
		</div>

		<div class="flex shrink-0 flex-wrap items-center gap-2">
			<h2 class="mr-auto text-lg-semibold text-ink-gray-8">Usage</h2>

			<template v-if="isCustom">
				<DateTimePicker
					:model-value="range.start ?? ''"
					placeholder="Start"
					aria-label="Start"
					format="D MMM YYYY, hh:mm a"
					class="w-52"
					@update:model-value="setRange({ start: $event || null })"
				/>

				<DateTimePicker
					:model-value="range.end ?? ''"
					placeholder="End"
					aria-label="End"
					format="D MMM YYYY, hh:mm a"
					class="w-52"
					@update:model-value="setRange({ end: $event || null })"
				/>
			</template>

			<Select
				:model-value="range.period"
				:options="METRIC_PERIODS"
				aria-label="Duration"
				class="w-32"
				@update:model-value="choosePeriod"
			/>

			<Button
				icon="lucide-refresh-cw"
				label="Refresh"
				:tooltip="freshness ?? undefined"
				@click="emit('refresh')"
			/>
		</div>

		<div
			v-if="charts.length"
			class="grid gap-3 md:grid-cols-2 lg:min-h-0 lg:flex-1 lg:grid-rows-2"
		>
			<ServerMetricChart
				v-for="chart in charts"
				:key="chart.key"
				:chart="chart"
				:time-grain="timeGrain"
			/>
		</div>

		<EmptyState
			v-else
			icon="lucide-chart-area"
			title="No samples in this period"
			description="The region has no measurements for this server in the chosen period. Choose another period, or wait for the next update if the server has just started."
		/>
	</div>

	<EmptyState
		v-else
		icon="lucide-chart-area"
		title="No usage yet"
		description="Charts appear while the server runs. The region samples it every 5 minutes."
	/>
</template>

<style scoped>
@media (min-width: 1024px) and (max-height: 740px) {
	.server-usage-grid :deep(.server-usage-card) {
		@apply space-y-1 p-2;
	}

	.server-usage-placeholder {
		@apply h-16;
	}
}
</style>
