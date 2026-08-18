<script setup lang="ts">
import {
	Button,
	Dropdown,
	type DropdownAlign,
	type DropdownOptions,
} from 'frappe-ui'

// One row's "⋯" action menu — the frappe-ui Dropdown + ghost ellipsis trigger that
// every *RowActions component repeated. Presentational: the caller builds `options`
// (each option's onClick emits its verb) and an empty list hides the whole menu.
// The trigger stops click propagation so opening the menu never triggers the row.
withDefaults(
	defineProps<{
		options: DropdownOptions
		/** Trigger aria-label, e.g. "Server actions". */
		label: string
		busy?: boolean
		icon?: string
		align?: DropdownAlign
	}>(),
	{ busy: false, icon: 'lucide-ellipsis-vertical', align: 'end' },
)
</script>

<template>
	<Dropdown v-if="options.length" :options="options" :align="align">
		<template #trigger>
			<!-- Inset focus ring: list cells clip horizontally, so an outside
			     focus outline gets sliced at the cell edge. -->
			<Button
				class="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-outline-gray-4"
				variant="ghost"
				:icon="icon"
				:loading="busy"
				:aria-label="label"
				@click.stop
			/>
		</template>
	</Dropdown>
</template>
