<script setup lang="ts">
import { Button, dayjs, Popover, Tooltip } from 'frappe-ui'
import { AreaChart, useChartTokens } from 'frappe-ui/charts'
import { computed, ref } from 'vue'
import MonthlyLimit from '@/components/services/llm/MonthlyLimit.vue'
import { useAI } from '@/composables/useAI'
import { formatDateTime, timeAgo } from '@/lib/datetime'
import { reportError, successToast } from '@/lib/feedback'
import { compactNumber, money, usd } from '@/lib/format'
import { __ } from '@/lib/translate'

interface Props {
	canManage: boolean
}

defineProps<Props>()

defineEmits<{ create: []; quickstart: [] }>()

const { ai, apiKeys, refreshing, refreshUsage } = useAI()

const usage = computed(() => ai.value?.usage)
const billingRate = computed(() => ai.value?.billing_rate ?? null)

// Usage in the team's billing currency at the month's rate, which its invoice uses too.
const billed = (cost: number | null | undefined): string => {
	const rate = billingRate.value
	return rate ? money((cost ?? 0) * rate.rate, rate.currency) : usd(cost)
}

const rateLabel = computed(() => {
	const rate = billingRate.value
	if (!rate) return ''
	const label = __('Rate for {0}: {1} per US$1', [
		dayjs(rate.month).format('MMMM'),
		money(rate.rate, rate.currency),
	])
	// The accounting system had no rate on the 1st, so the latest earlier one is used.
	return dayjs(rate.rate_date).isBefore(rate.month)
		? __('{0}, the rate of {1}', [
				label,
				dayjs(rate.rate_date).format('D MMMM'),
			])
		: label
})

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
		class="overflow-hidden rounded-8 border border-outline-gray-2 bg-surface-base"
	>
		<div v-if="hasTraffic" class="flex flex-col gap-3 px-4 py-4 md:px-6">
			<div class="flex items-center justify-between gap-3">
				<div
					class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 sm:gap-x-5"
				>
					<h2 class="flex items-center gap-1.5 text-sm-medium text-ink-gray-6">
						<span
							class="lucide-calendar-days size-4 text-ink-gray-4"
							aria-hidden="true"
						/>
						{{ monthLabel }}
					</h2>
					<p
						v-if="rateLabel"
						class="hidden items-center gap-1.5 text-sm text-ink-gray-5 sm:flex"
					>
						<span
							class="lucide-tag size-3.5 shrink-0 text-ink-gray-4"
							aria-hidden="true"
						/>
						{{ rateLabel }}
					</p>
					<Popover v-if="rateLabel" align="start" arrow>
						<template #trigger>
							<Button
								class="-my-1 !rounded-full !text-ink-gray-4 sm:hidden"
								variant="ghost"
								size="xs"
								icon="lucide-tag"
								label="Billing rate"
							/>
						</template>
						<p class="max-w-64 px-3 py-2 text-sm text-ink-gray-7">
							{{ rateLabel }}
						</p>
					</Popover>
				</div>

				<div class="flex shrink-0 items-center gap-1 text-sm text-ink-gray-5">
					<Tooltip
						v-if="usage?.as_of"
						:text="`Counted ${formatDateTime(usage.as_of)}`"
					>
						<span class="hidden sm:inline"
							>Updated {{ timeAgo(usage.as_of) }}</span
						>
					</Tooltip>
					<Tooltip text="Refresh usage">
						<Button
							class="-my-1 -mr-1.5 !rounded-full !text-ink-gray-5 hover:!text-ink-gray-8"
							variant="ghost"
							size="xs"
							icon="lucide-refresh-cw"
							label="Refresh usage"
							:loading="refreshing"
							@click="refresh"
						/>
					</Tooltip>
				</div>
			</div>

			<div class="grid gap-4 lg:grid-cols-7 lg:gap-6">
				<div class="flex min-w-0 flex-col lg:col-span-4">
					<p class="truncate text-8xl-semibold tabular-nums text-ink-gray-9">
						{{ billed(usage?.cost) }}
					</p>
					<p class="mt-1 flex items-start gap-2 text-p-base text-ink-gray-5">
						<span
							class="lucide-chart-no-axes-column mt-0.5 size-4 shrink-0 text-ink-gray-6"
							aria-hidden="true"
						/>
						<span>
							Spent this month on
							<span class="tabular-nums text-ink-gray-9"
								>{{ usage?.requests.toLocaleString() }}</span
							>
							requests and
							<Tooltip
								:text="`${usage?.tokens.toLocaleString()} input and output tokens`"
							>
								<span class="tabular-nums text-ink-gray-9"
									>{{ compactNumber(usage?.tokens ?? 0) }}</span
								>
							</Tooltip>
							tokens.
						</span>
					</p>
					<MonthlyLimit class="mt-3 border-t border-outline-gray-1 pt-3" />
				</div>

				<figure
					class="pace-chart flex min-w-0 flex-col gap-2 rounded-7 border border-outline-gray-1 bg-surface-gray-1 px-3.5 pb-3 pt-2.5 lg:col-span-3"
				>
					<div
						class="min-h-12 flex-1"
						role="img"
						:aria-label="`Spend this month so far, on pace for ${billed(projected)} by ${monthEnd}`"
					>
						<AreaChart
							:data="paceDays"
							x="day"
							:x-axis="{ type: 'category' }"
							:y="['spent', 'pace']"
							:series-config="paceSeries"
							:y-axis="{ min: 0, format: billed }"
							:echart-options="bareChart"
						/>
					</div>
					<figcaption class="text-xs text-ink-gray-5">
						On pace for
						<span class="tabular-nums text-ink-gray-9"
							>{{ billed(projected) }}</span
						>
						by {{ monthEnd }}
					</figcaption>
				</figure>
			</div>
		</div>

		<div v-else class="flex flex-col gap-5 px-4 py-3.5 md:px-5 md:py-4.5">
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
						:disabled="ai?.key_handover_pending"
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

			<MonthlyLimit
				class="rounded-5 bg-surface-gray-1 px-3 py-2.5 sm:max-w-xs"
			/>
		</div>
	</section>
</template>

<style scoped>
.pace-chart :deep([data-slot="chart-legend"]) {
	display: none;
}
</style>
