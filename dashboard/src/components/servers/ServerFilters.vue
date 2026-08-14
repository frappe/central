<script setup lang="ts">
import { Combobox, type ComboboxOption } from 'frappe-ui'
import type { ServerVisual } from '@/lib/serverMap'

// The top-right status + region filters over the map. Both scope the map pins
// and the panel rows; the page owns the option lists and the resolved filters.
//
// Combobox in its default `input` trigger: typing happens in the trigger
// itself, so the popover below is nothing but the option list — no search row
// stacked inside it, and the list opens under the input rather than over it.
defineProps<{
	statusOptions: { label: string; value: string; dot?: string }[]
	/** Grouped by provider, so this is Combobox's option union, not a flat list. */
	regionOptions: ComboboxOption[]
}>()

const statusFilter = defineModel<ServerVisual['key'] | ''>('statusFilter', {
	required: true,
})
const regionSelection = defineModel<string>('regionSelection', {
	required: true,
})
</script>

<template>
	<!-- Side by side these two run past the right edge of a phone, and into the
	     list pill on the left. Stack them under each other until there's room. -->
	<div
		class="absolute right-4 top-4 flex flex-col items-end gap-2 sm:flex-row sm:items-center"
	>
		<Combobox
			v-model="statusFilter"
			variant="outline"
			size="md"
			align="end"
			class="w-40"
			:options="statusOptions"
		>
			<template #item-prefix="{ item }">
				<span
					class="size-2 shrink-0 rounded-full transition-colors"
					:style="{ background: item.dot || 'var(--ink-gray-4)' }"
				/>
			</template>
		</Combobox>
		<Combobox
			v-model="regionSelection"
			variant="outline"
			size="md"
			align="end"
			class="w-40"
			:options="regionOptions"
		/>
	</div>
</template>
