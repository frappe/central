<script setup lang="ts">
import { Button, dayjs, Tooltip } from 'frappe-ui'
import { AreaChart, useChartTokens } from 'frappe-ui/charts'
import { computed, ref } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import { useAI } from '@/composables/useAI'
import { formatDateTime, timeAgo } from '@/lib/datetime'
import { reportError, successToast } from '@/lib/feedback'
import { compactNumber, usd } from '@/lib/format'

interface Props {
	canManage: boolean
}

defineProps<Props>()

defineEmits<{ create: []; quickstart: [] }>()

const { ai, apiKeys, refreshing, refreshUsage } = useAI()

const usage = computed(() => ai.value?.usage)
const spend = computed(() => ai.value?.spend)

const hasTraffic = computed(() => (usage.value?.requests ?? 0) > 0)
const activeKeyCount = computed(
	() => apiKeys.value.filter((key) => key.status === 'active').length,
)

const monthLabel = computed(() => {
	const from = dayjs(usage.value?.from_date)
	const to = dayjs(usage.value?.to_date)

	return from.isValid() && to.isValid()
		? `${from.format('D')} – ${to.format('D MMMM')}`
		: 'This month'
})

const projected = computed(() => {
	const from = dayjs(usage.value?.from_date)
	const elapsed = dayjs(usage.value?.to_date).diff(from, 'day') + 1
	return elapsed > 0
		? ((usage.value?.cost ?? 0) / elapsed) * from.daysInMonth()
		: 0
})

const monthEnd = computed(() =>
	dayjs(usage.value?.from_date).endOf('month').format('D MMMM'),
)

const paceDays = computed(() => {
	const days = usage.value?.daily ?? []
	const from = dayjs(usage.value?.from_date)
	const daily = days.length ? (usage.value?.cost ?? 0) / days.length : 0
	let spent = 0
	return Array.from({ length: from.daysInMonth() }, (_, index) => {
		const day = from.add(index, 'day').format('YYYY-MM-DD')
		if (index < days.length) spent += days[index].cost
		const isPast = index < days.length
		return {
			day,
			spent: isPast ? spent : null,
			pace:
				index >= days.length - 1
					? spent + daily * (index - days.length + 1)
					: null,
		}
	})
})

const { tokens: chartTokens } = useChartTokens(ref())
const themeColor = (name: string): string => {
	void chartTokens.value
	return getComputedStyle(document.documentElement)
		.getPropertyValue(`--${name}`)
		.trim()
}

const paceSeries = computed(() => {
	const ink = themeColor('ink-gray-9')
	return {
		spent: {
			label: 'Spent',
			color: ink,
			echartOptions: {
				lineStyle: { width: 1.5 },
				areaStyle: {
					opacity: 0.15,
					color: {
						type: 'linear',
						x: 0,
						y: 0,
						x2: 0,
						y2: 1,
						colorStops: [
							{ offset: 0, color: ink },
							{ offset: 1, color: themeColor('surface-gray-1') },
						],
					},
				},
			},
		},
		pace: {
			label: 'At this pace',
			type: 'line' as const,
			dashed: true,
			color: themeColor('ink-gray-4'),
			echartOptions: { lineStyle: { width: 1.5 } },
		},
	}
})

const bareChart = {
	grid: { top: 4, right: 2, bottom: 2, left: 2, outerBoundsMode: 'none' },
	xAxis: { show: false, boundaryGap: false },
	yAxis: { show: false },
}

const limitPercent = computed(() => {
	const limit = spend.value?.spend_limit ?? 0
	return limit > 0
		? Math.min(((spend.value?.committed ?? 0) / limit) * 100, 100)
		: 0
})

const limitBarClass = computed(() =>
	limitPercent.value >= 100
		? 'bg-surface-red-5'
		: limitPercent.value >= 80
			? 'bg-surface-amber-7'
			: 'bg-surface-gray-7',
)

const keysLabel = computed(() => {
	const max = spend.value?.max_keys ?? 0
	return max > 0
		? `${activeKeyCount.value} of ${max}`
		: String(activeKeyCount.value)
})

const gateway = computed(() => {
	const geographies = (ai.value?.geographies ?? []).filter((g) => g.endpoint)
	return geographies.find((g) => g.is_default) ?? geographies[0]
})

const hasManyGeographies = computed(
	() => (ai.value?.geographies ?? []).filter((g) => g.endpoint).length > 1,
)

const refresh = async (): Promise<void> => {
	try {
		await refreshUsage()
		successToast('Usage refreshed.')
	} catch (e) {
		reportError(e, { title: 'Could not refresh usage' })
	}
}
</script>

<template>
	<section
		class="grid overflow-hidden rounded-6 border border-outline-gray-2 bg-surface-base lg:grid-cols-3"
	>
		<div
			v-if="hasTraffic"
			class="flex flex-col justify-between gap-3 px-4 py-3.5 md:px-5 md:py-4.5 lg:col-span-2"
		>
			<div class="flex items-center justify-between gap-3">
				<h2 class="flex items-center gap-1.5 text-sm-medium text-ink-gray-6">
					<span
						class="lucide-calendar size-4 text-ink-gray-4"
						aria-hidden="true"
					/>
					{{ monthLabel }}
				</h2>

				<div class="flex items-center gap-1">
					<Tooltip
						v-if="usage?.as_of"
						:text="`Counted ${formatDateTime(usage.as_of)}`"
					>
						<span class="text-sm text-ink-gray-5">
							Updated {{ timeAgo(usage.as_of) }}
						</span>
					</Tooltip>
					<Tooltip text="Refresh usage">
						<Button
							class="-my-1"
							variant="ghost"
							size="xs"
							label="Refresh usage"
							icon="lucide-refresh-cw"
							:loading="refreshing"
							@click="refresh"
						/>
					</Tooltip>
				</div>
			</div>

			<div
				class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-8"
			>
				<div class="min-w-0">
					<p class="text-8xl-semibold tabular-nums text-ink-gray-9">
						{{ usd(usage?.cost) }}
					</p>
					<p class="mt-2 text-p-base text-ink-gray-5">
						Spent this month on
						<span class="tabular-nums text-ink-gray-7"
							>{{ usage?.requests.toLocaleString() }}</span
						>
						requests and
						<Tooltip
							:text="`${usage?.tokens.toLocaleString()} input and output tokens`"
						>
							<span class="tabular-nums text-ink-gray-7"
								>{{ compactNumber(usage?.tokens ?? 0) }}</span
							>
						</Tooltip>
						tokens.
					</p>
				</div>
				<figure
					class="pace-chart flex w-full shrink-0 flex-col gap-2 rounded-5 bg-surface-gray-1 px-3 py-2.5 sm:w-fit"
				>
					<div
						class="h-16"
						role="img"
						:aria-label="`Spend this month so far, on pace for ${usd(projected)} by ${monthEnd}`"
					>
						<AreaChart
							:data="paceDays"
							x="day"
							:x-axis="{ type: 'category' }"
							:y="['spent', 'pace']"
							:series-config="paceSeries"
							:y-axis="{ min: 0, format: usd }"
							:echart-options="bareChart"
						/>
					</div>
					<figcaption class="text-xs text-ink-gray-5">
						<span>
							On pace for
							<span class="tabular-nums text-ink-gray-8"
								>{{ usd(projected) }}</span
							>
							by {{ monthEnd }}
						</span>
					</figcaption>
				</figure>
			</div>
		</div>

		<div
			v-else
			class="flex flex-col gap-5 px-4 py-3.5 md:px-5 md:py-4.5 lg:col-span-2"
		>
			<div>
				<h2 class="text-lg-semibold text-ink-gray-9">
					Make your first request
				</h2>
				<p class="mt-1 text-p-base text-ink-gray-6">
					Any OpenAI or Anthropic SDK works. Point it at your base URL and pass
					a key.
				</p>
			</div>

			<ol class="flex flex-col">
				<li class="flex items-center gap-3 border-b border-outline-gray-1 pb-3">
					<span
						v-if="activeKeyCount"
						class="lucide-circle-check size-6 shrink-0 text-ink-green-6"
						aria-label="Done"
					/>
					<span
						v-else
						class="grid size-6 shrink-0 place-items-center rounded-full border border-outline-gray-3 text-xs-medium text-ink-gray-6"
					>
						1
					</span>
					<span
						class="flex-1 text-base"
						:class="activeKeyCount ? 'text-ink-gray-5' : 'text-ink-gray-8'"
					>
						Create an API key
					</span>
					<Button
						v-if="!activeKeyCount && canManage"
						variant="solid"
						label="Create key"
						@click="$emit('create')"
					/>
				</li>

				<li class="flex items-center gap-3 border-b border-outline-gray-1 py-3">
					<span
						class="grid size-6 shrink-0 place-items-center rounded-full border border-outline-gray-3 text-xs-medium text-ink-gray-6"
					>
						2
					</span>
					<span class="flex-1 text-base text-ink-gray-8">
						Set the base URL in your SDK
					</span>
				</li>

				<li class="flex items-center gap-3 pt-3">
					<span
						class="grid size-6 shrink-0 place-items-center rounded-full border border-outline-gray-3 text-xs-medium text-ink-gray-6"
					>
						3
					</span>
					<span class="flex-1 text-base text-ink-gray-8">Send a request</span>
					<Button
						label="See examples"
						icon-right="lucide-arrow-right"
						@click="$emit('quickstart')"
					/>
				</li>
			</ol>
		</div>

		<dl
			class="flex flex-col gap-4 border-t border-outline-gray-2 px-4 py-3.5 text-base md:px-5 md:py-4.5 lg:border-l lg:border-t-0"
		>
			<div class="flex flex-col gap-2">
				<div class="flex items-center justify-between gap-3">
					<dt class="flex items-center gap-1.5 text-ink-gray-5">
						Monthly limit
						<Tooltip
							text="Your keys' caps and this month's spend, out of what your plan allows a month. Usage is billed at the end of the month."
						>
							<span
								class="lucide-info size-3.5 text-ink-gray-4"
								aria-label="What the monthly limit is"
							/>
						</Tooltip>
					</dt>
					<dd v-if="spend?.spend_limit" class="tabular-nums text-ink-gray-5">
						<span class="text-base-medium text-ink-gray-9">
							{{ usd(spend.committed) }}
						</span>
						/ {{ usd(spend.spend_limit) }}
					</dd>
					<dd v-else class="text-ink-gray-5">Not on your plan</dd>
				</div>
				<div
					v-if="spend?.spend_limit"
					class="h-1 overflow-hidden rounded-full bg-surface-gray-2"
					role="meter"
					:aria-valuenow="Math.round(limitPercent)"
					aria-valuemin="0"
					aria-valuemax="100"
					aria-label="Share of the monthly limit taken"
				>
					<div
						class="h-full rounded-full transition-[width] duration-300 ease-out"
						:class="limitBarClass"
						:style="{ width: `${limitPercent}%` }"
					/>
				</div>
			</div>

			<div class="flex items-center justify-between gap-3">
				<dt class="text-ink-gray-5">Live keys</dt>
				<dd class="tabular-nums text-ink-gray-8">{{ keysLabel }}</dd>
			</div>

			<div v-if="gateway?.endpoint" class="flex flex-col gap-1.5">
				<dt class="text-ink-gray-5">
					Gateway<template v-if="hasManyGeographies">
						· {{ gateway.label }}</template
					>
				</dt>
				<dd>
					<CopyableValue :value="gateway.endpoint" label="Gateway URL" />
				</dd>
			</div>
		</dl>
	</section>
</template>

<style scoped>
.pace-chart :deep([data-slot="chart-legend"]) {
	display: none;
}
</style>
