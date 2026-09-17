<script setup lang="ts">
// A row of equal picture-and-label cards for one choice: providers, images, anything
// else the creation form asks for. One component so every such row keeps the same card
// size — they drift apart as soon as the markup is copied.
export interface Choice {
	label: string
	value: string
}

defineProps<{
	modelValue: string | null
	options: Choice[]
	/** Names the group for assistive technology; the step heading shows it on screen. */
	label: string
	disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
	<fieldset
		:disabled="disabled"
		class="grid grid-cols-3 gap-2 sm:grid-cols-5"
		:aria-label="label"
	>
		<button
			v-for="option in options"
			:key="option.value"
			type="button"
			:aria-pressed="modelValue === option.value"
			:class="[
				'flex w-full flex-col items-center gap-1 rounded-6 border p-2 transition-colors',
				'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-outline-gray-4',
				'disabled:cursor-not-allowed disabled:opacity-50',
				modelValue === option.value
					? 'border-outline-gray-4 bg-surface-gray-1'
					: 'border-outline-gray-2 hover:bg-surface-gray-1',
			]"
			@click="emit('update:modelValue', option.value)"
		>
			<slot name="icon" :option="option" />
			<span class="truncate text-xs text-ink-gray-7">{{ option.label }}</span>
		</button>
	</fieldset>
</template>
