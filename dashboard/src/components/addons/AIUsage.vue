<script setup lang="ts">
import { Button, Select } from 'frappe-ui'
import { AreaChart, BarChart, NumberCard } from 'frappe-ui/charts'
import { computed, ref, watch } from 'vue'
import { useServices } from '@/composables/useServices'

interface Props {
	managedService: string
}

const props = defineProps<Props>()

const { usage, usageLoading, usageError, loadUsage } = useServices()

// The periods the provider knows by name.
const periodOptions = [
	'Today',
	'Yesterday',
	'Last 7 Days',
	'Last 30 Days',
	'This Month',
	'Last Month',
].map((name) => ({ label: name, value: name }))

const period = ref('Last 7 Days')

const reload = (): void => {
	if (props.managedService) loadUsage(props.managedService, period.value)
}

watch([() => props.managedService, period], reload, { immediate: true })

const totals = computed(() => usage.value?.totals ?? null)
const models = computed(() => usage.value?.models ?? [])
const daily = computed(() => usage.value?.daily ?? [])

const daysOf = (model: string) =>
	daily.value.filter((row) => row.model === model)

// A series is named by a model id. Shown as is, not reworded.
const modelSeries = computed(() =>
	Object.fromEntries(
		models.value.map((row) => [row.model, { label: row.model }]),
	),
)

// A model call often costs a fraction of a cent, so small amounts keep 4 places.
const costPrecision = computed(() => {
	const cost = totals.value?.cost ?? 0
	return cost > 0 && cost < 1 ? 4 : 2
})

const usd = (value: number): string =>
	new Intl.NumberFormat(undefined, {
		style: 'currency',
		currency: 'USD',
		minimumFractionDigits: 2,
		maximumFractionDigits: 4,
	}).format(value)

const compact = (value: number): string =>
	new Intl.NumberFormat(undefined, {
		notation: 'compact',
		maximumFractionDigits: 1,
	}).format(value)

// "2026-09-24" reads as "9/24" on the axis.
const shortDay = (day: string): string => {
	const [, month, date] = day.split('-')
	return `${Number(month)}/${Number(date)}`
}

const dayAxis = { type: 'category' as const, format: shortDay }

const asOf = computed(() =>
	usage.value?.as_of ? new Date(usage.value.as_of).toLocaleString() : null,
)
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl space-y-5 px-6 pb-8 pt-5">
			<Select
				v-model="period"
				:options="periodOptions"
				variant="outline"
				aria-label="Period"
			/>

			<div class="flex flex-wrap gap-4">
				<NumberCard
					class="min-w-40 flex-1"
					title="Cost"
					:value="totals?.cost ?? null"
					prefix="$"
					:precision="costPrecision"
					:loading="usageLoading"
				/>
				<NumberCard
					class="min-w-40 flex-1"
					title="API requests"
					:value="totals?.requests ?? null"
					:loading="usageLoading"
				/>
			</div>

			<div
				v-if="usageError"
				class="flex items-center justify-between gap-3 rounded-6 border border-outline-gray-2 p-5"
			>
				<p class="text-p-sm text-ink-gray-7">Usage could not be loaded.</p>
				<Button label="Try again" @click="reload" />
			</div>

			<p
				v-else-if="usage && !models.length"
				class="rounded-6 border border-outline-gray-2 p-8 text-center text-p-sm text-ink-gray-5"
			>
				No data available
			</p>

			<template v-else>
				<section
					class="h-80 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
				>
					<BarChart
						title="Cost (USD)"
						:subtitle="totals ? usd(totals.cost) : undefined"
						:data="daily"
						x="day"
						y="cost"
						series="model"
						:series-config="modelSeries"
						stacked
						:x-axis="dayAxis"
						:y-axis="{ format: usd }"
						:loading="usageLoading"
					/>
				</section>

				<section v-for="row in models" :key="row.model" class="space-y-3">
					<h2 class="font-mono text-sm font-semibold text-ink-gray-8">
						{{ row.model }}
					</h2>

					<div class="grid gap-4 md:grid-cols-2">
						<div
							class="h-72 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
						>
							<AreaChart
								title="API requests"
								:subtitle="row.requests.toLocaleString()"
								:data="daysOf(row.model)"
								x="day"
								y="requests"
								:series-config="{
									requests: { label: 'Requests', smooth: true },
								}"
								:x-axis="dayAxis"
								:y-axis="{ min: 0, format: compact }"
							/>
						</div>

						<div
							class="h-72 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
						>
							<BarChart
								title="Cost (USD)"
								:subtitle="usd(row.cost)"
								:data="daysOf(row.model)"
								x="day"
								y="cost"
								:series-config="{ cost: { label: 'Cost' } }"
								:x-axis="dayAxis"
								:y-axis="{ format: usd }"
							/>
						</div>
					</div>
				</section>
			</template>

			<p v-if="asOf" class="text-p-xs text-ink-gray-5">
				Usage up to {{ asOf }}. Days are in UTC.
			</p>
		</div>
	</div>
</template>
