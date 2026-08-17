<script setup lang="ts" generic="T">
import { Dialog, ErrorMessage } from 'frappe-ui'
import { computed } from 'vue'

// One confirm dialog for the "hold a pending target, ask before acting" pattern.
// Controlled by the caller: bind the pending item (or null) with v-model:target —
// null closes it. Emits confirm(target) for the caller to run the mutation; pass
// :loading while it runs. On failure the caller keeps the target set and passes :error,
// so the dialog stays open with the reason inline instead of vanishing behind a toast.
const props = withDefaults(
	defineProps<{
		target: T | null
		title: string
		message?: string
		confirmLabel?: string
		/** Set 'red' for a destructive action; omit for a neutral solid confirm. */
		theme?: 'red'
		loading?: boolean
		error?: string
	}>(),
	{ confirmLabel: 'Confirm' },
)

const emit = defineEmits<{
	'update:target': [value: T | null]
	confirm: [value: T]
}>()

const open = computed({
	get: () => props.target !== null,
	set: (isOpen: boolean) => {
		if (!isOpen) emit('update:target', null)
	},
})

const actions = computed(() => [
	{
		label: props.confirmLabel,
		variant: 'solid' as const,
		theme: props.theme,
		loading: props.loading,
		onClick: () => {
			if (props.target !== null) emit('confirm', props.target)
		},
	},
])
</script>

<template>
	<Dialog
		v-model="open"
		:title="title"
		:message="message"
		size="sm"
		:actions="actions"
	>
		<slot />
		<ErrorMessage v-if="error" class="mt-2" :message="error" />
	</Dialog>
</template>
