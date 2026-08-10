<script setup lang="ts">
import {
	Button,
	Dropdown,
	type DropdownOptions,
	type DropdownPlacement,
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
		placement?: DropdownPlacement
	}>(),
	{ busy: false, icon: 'lucide-ellipsis-vertical', placement: 'right' },
)
</script>

<template>
	<Dropdown v-if="options.length" :options="options" :placement="placement">
		<template #trigger>
			<Button
				variant="ghost"
				:icon="icon"
				:loading="busy"
				:aria-label="label"
				@click.stop
			/>
		</template>
	</Dropdown>
</template>
