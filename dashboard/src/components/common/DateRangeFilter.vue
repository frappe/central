<script setup lang="ts">
import dayjs from 'dayjs'
import { DateRangePicker } from 'frappe-ui'
import { computed } from 'vue'
import { parseDateRange } from '@/lib/dateRange'

/** A list filter for a date range, with one-click presets and a clear option. */
export interface DateRangePreset {
	label: string
	range: () => [string, string]
}

interface Props {
	presets: DateRangePreset[]
	/** Placeholder and clear label when no range is set. */
	anyLabel?: string
}

const props = withDefaults(defineProps<Props>(), { anyLabel: 'Any date' })

// [fromISO, toISO]; empty means any date
const range = defineModel<string[]>({ default: () => [] })
const today = dayjs().format('YYYY-MM-DD')
const currentYear = today.slice(0, 4)

const labelFormat = computed(() => {
	const otherYear = range.value.some(
		(date) => Boolean(date) && date.slice(0, 4) !== currentYear,
	)
	return otherYear ? 'D MMM YYYY' : 'D MMM'
})

function matchPreset(value: string): [string, string] | null {
	const query = value.toLowerCase()
	if (query.length < 3) return null
	const preset = props.presets.find((item) =>
		item.label.toLowerCase().startsWith(query),
	)
	return preset ? preset.range() : null
}

function normalizeTyped(event: Event): void {
	const input = event.target
	if (!(input instanceof HTMLInputElement)) return

	const value = input.value.trim()
	if (!value) return

	const resolved = parseDateRange(value, today) ?? matchPreset(value)
	if (resolved) {
		input.value = `${resolved[0]} to ${resolved[1]}`
	} else {
		input.value =
			range.value.length === 2 ? `${range.value[0]} to ${range.value[1]}` : ''
	}
	input.dispatchEvent(new Event('input'))
}
</script>

<template>
	<div
		class="flex-1 md:w-44"
		@keydown.enter.capture="normalizeTyped"
		@blur.capture="normalizeTyped"
	>
		<DateRangePicker
			v-model="range"
			class="w-full"
			size="sm"
			:format="labelFormat"
			:placeholder="anyLabel"
			:max="today"
		>
			<template #prefix>
				<span
					class="lucide-calendar size-4 text-ink-gray-4"
					aria-hidden="true"
				/>
			</template>
			<template #actions="{ setRange, clear, close }">
				<button
					v-for="preset in presets"
					:key="preset.label"
					type="button"
					class="w-full rounded-4 px-2 py-1.5 text-left text-base text-ink-gray-7 hover:bg-surface-gray-2"
					@click="() => { setRange(preset.range()); close() }"
				>
					{{ preset.label }}
				</button>
				<button
					type="button"
					class="w-full rounded-4 px-2 py-1.5 text-left text-base text-ink-gray-5 hover:bg-surface-gray-2"
					@click="() => { clear(); close() }"
				>
					{{ anyLabel }}
				</button>
			</template>
		</DateRangePicker>
	</div>
</template>
