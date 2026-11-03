<script setup lang="ts">
import dayjs from 'dayjs'
import { DateRangePicker } from 'frappe-ui'

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

withDefaults(defineProps<Props>(), { anyLabel: 'Any date' })

// [fromISO, toISO]; empty means any date
const range = defineModel<string[]>({ default: () => [] })
const today = dayjs().format('YYYY-MM-DD')
</script>

<template>
	<DateRangePicker
		v-model="range"
		class="flex-1 md:w-44"
		size="sm"
		format="D MMM"
		:placeholder="anyLabel"
		:max="today"
	>
		<template #prefix>
			<span class="lucide-calendar size-4 text-ink-gray-4" aria-hidden="true" />
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
</template>
