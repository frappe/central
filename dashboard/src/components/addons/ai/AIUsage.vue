<script setup lang="ts">
import { Button, Select } from 'frappe-ui'
import { AreaChart, BarChart } from 'frappe-ui/charts'
import { computed, ref, watch } from 'vue'
import { useAI } from '@/composables/useAI'

const { usage, usageLoading, usageError, loadUsage, apiKeys, loadApiKeys } =
	useAI()

// The periods the provider knows by name.
const periodOptions = [
	{ label: 'Today', value: 'Today' },
	{ label: 'Yesterday', value: 'Yesterday' },
	{ label: 'Last 7 days', value: 'Last 7 Days' },
	{ label: 'Last 30 days', value: 'Last 30 Days' },
	{ label: 'This month', value: 'This Month' },
	{ label: 'Last month', value: 'Last Month' },
]

const defaultPeriod = 'Last 7 Days'
const period = ref(defaultPeriod)

// '' is every key. A revoked key keeps its history, so it stays in the list.
const apiKey = ref('')
const keyOptions = computed(() => [
	{ label: 'All', value: '' },
	...apiKeys.value.map((key) => ({
		label: key.status === 'active' ? key.title : `${key.title} (revoked)`,
		value: key.name,
	})),
])

loadApiKeys()

const isFiltered = computed(
	() => period.value !== defaultPeriod || apiKey.value !== '',
)

const resetFilters = (): void => {
	period.value = defaultPeriod
	apiKey.value = ''
}

const reload = (): void => {
	loadUsage({ period: period.value, key: apiKey.value })
}

watch([period, apiKey], reload, { immediate: true })

const totals = computed(() => usage.value?.totals ?? null)
const models = computed(() => usage.value?.models ?? [])
const daily = computed(() => usage.value?.daily ?? [])

// One model's charts at a time, so a long model list does not take the whole page.
// Models come costliest first, so the first is the default.
const selectedModel = ref('')
const modelOptions = computed(() =>
	models.value.map((row) => ({ label: row.model, value: row.model })),
)
const selected = computed(
	() => models.value.find((row) => row.model === selectedModel.value) ?? null,
)
const selectedDays = computed(() =>
	daily.value.filter((row) => row.model === selectedModel.value),
)

watch(models, (rows) => {
	if (!rows.some((row) => row.model === selectedModel.value))
		selectedModel.value = rows[0]?.model ?? ''
})

// A series is named by a model id. Shown as is, not reworded.
const modelSeries = computed(() =>
	Object.fromEntries(
		models.value.map((row) => [row.model, { label: row.model }]),
	),
)

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
			<!-- Sits on the page's tab row, so the page has one row of pills. -->
			<Teleport defer to="#ai-tab-controls">
				<div class="flex flex-wrap items-center gap-2">
					<Select
						v-model="period"
						:options="periodOptions"
						side="bottom"
						align="start"
						aria-label="Time"
					>
						<template #prefix>
							<span class="text-ink-gray-5">Time</span>
						</template>
					</Select>
					<Select
						v-model="apiKey"
						:options="keyOptions"
						side="bottom"
						align="start"
						aria-label="API key"
					>
						<template #prefix>
							<span class="text-ink-gray-5">API Key</span>
						</template>
					</Select>
					<button
						v-if="isFiltered"
						type="button"
						class="text-p-sm text-ink-gray-7 underline underline-offset-2 hover:text-ink-gray-9"
						@click="resetFilters"
					>
						Reset filters
					</button>
				</div>
			</Teleport>

			<div
				v-if="usageError"
				class="flex items-center justify-between gap-3 rounded-6 border border-outline-gray-2 p-5"
			>
				<p class="text-p-sm text-ink-gray-7">Usage could not be loaded.</p>
				<Button label="Try again" @click="reload" />
			</div>

			<p
				v-else-if="usage && !models.length && !usageLoading"
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

				<section v-if="selected" class="space-y-3">
					<Select
						v-model="selectedModel"
						:options="modelOptions"
						side="bottom"
						align="start"
						aria-label="Model"
						class="w-fit"
					>
						<template #prefix>
							<span class="text-ink-gray-5">Model</span>
						</template>
					</Select>

					<div class="grid gap-4 md:grid-cols-2">
						<div
							class="h-72 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
						>
							<AreaChart
								title="API requests"
								:subtitle="selected.requests.toLocaleString()"
								:data="selectedDays"
								x="day"
								y="requests"
								:series-config="{
									requests: { label: 'Requests', smooth: true },
								}"
								:x-axis="dayAxis"
								:y-axis="{ min: 0, format: compact }"
								:loading="usageLoading"
							/>
						</div>

						<div
							class="h-72 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
						>
							<BarChart
								title="Cost (USD)"
								:subtitle="usd(selected.cost)"
								:data="selectedDays"
								x="day"
								y="cost"
								:series-config="{ cost: { label: 'Cost' } }"
								:x-axis="dayAxis"
								:y-axis="{ format: usd }"
								:loading="usageLoading"
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
