<script setup lang="ts" generic="T">
import { Button, Dialog, ErrorMessage } from 'frappe-ui'
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
		/** Keep the confirm button off, with the reason in the body. */
		disabled?: boolean
		error?: string
		/** Widen it when the body holds more than a sentence, such as a list. */
		size?: 'sm' | 'md' | 'lg'
	}>(),
	{ confirmLabel: 'Confirm', size: 'sm' },
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

// Dialog's `actions` prop resets each action's `loading`, so the button is rendered here
// to show the caller's :loading while the mutation runs.
function confirm(): void {
	if (props.target !== null) emit('confirm', props.target)
}
</script>

<template>
	<Dialog v-model="open" :title="title" :message="message" :size="size">
		<slot />
		<ErrorMessage v-if="error" class="mt-2" :message="error" />
		<template #actions>
			<div :class="size === 'lg' ? 'flex justify-end' : ''">
				<Button
					:class="size === 'lg' ? '' : 'w-full'"
					variant="solid"
					:theme="theme"
					:label="confirmLabel"
					:loading="loading"
					:disabled="disabled"
					@click="confirm"
				/>
			</div>
		</template>
	</Dialog>
</template>
