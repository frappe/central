<script setup lang="ts">
import { Tooltip } from 'frappe-ui'

interface Props {
	label: string
	/** Shown on hover, for a detail the label leaves out. */
	tooltip?: string
	/** The accessible name of the remove button. Without it, the chip cannot be removed. */
	removeLabel?: string
}

defineProps<Props>()
const emit = defineEmits<{ remove: [] }>()
</script>

<template>
	<span
		class="inline-flex h-6 items-center gap-1 rounded-3 bg-surface-base pl-2 text-sm text-ink-gray-8"
		:class="removeLabel ? 'pr-1' : 'pr-2'"
	>
		<Tooltip :text="tooltip">
			<span :tabindex="tooltip ? 0 : undefined">{{ label }}</span>
		</Tooltip>
		<button
			v-if="removeLabel"
			type="button"
			class="grid size-4 place-items-center rounded-2 text-ink-gray-5 hover:bg-surface-gray-3 hover:text-ink-gray-8 focus-visible:focus-ring"
			:aria-label="removeLabel"
			@click="emit('remove')"
		>
			<span class="lucide-x size-3" aria-hidden="true" />
		</button>
	</span>
</template>
