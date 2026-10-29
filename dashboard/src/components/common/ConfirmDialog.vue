<script setup lang="ts" generic="T">
import { Button, Dialog, ErrorMessage, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

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
		/** For an action that destroys data: the person types this text to turn the button on. */
		confirmText?: string
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

const typedText = ref('')
watch(
	() => props.target,
	() => {
		typedText.value = ''
	},
)
const isBlocked = computed(
	() =>
		props.disabled ||
		(!!props.confirmText && typedText.value.trim() !== props.confirmText),
)

// Dialog's `actions` prop resets each action's `loading`, so the button is rendered here
// to show the caller's :loading while the mutation runs.
function confirm(): void {
	if (props.target !== null && !isBlocked.value && !props.loading)
		emit('confirm', props.target)
}
</script>

<template>
	<Dialog v-model="open" :title="title" :message="message" :size="size">
		<slot />
		<TextInput
			v-if="confirmText"
			v-model="typedText"
			class="mt-4"
			autocomplete="off"
			:label="`Type ${confirmText} to confirm`"
			@keydown.enter="confirm"
		/>
		<ErrorMessage v-if="error" class="mt-2" :message="error" />
		<template #actions>
			<div :class="size === 'lg' ? 'flex justify-end' : ''">
				<Button
					:class="size === 'lg' ? '' : 'w-full'"
					variant="solid"
					:theme="theme"
					:label="confirmLabel"
					:loading="loading"
					:disabled="isBlocked"
					@click="confirm"
				/>
			</div>
		</template>
	</Dialog>
</template>
