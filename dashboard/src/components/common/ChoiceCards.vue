<script setup lang="ts">
export interface Choice {
	label: string
	value: string
	description?: string
}

interface Props {
	modelValue: string | null
	options: Choice[]
	label: string
	columns?: 2 | 3
	disabled?: boolean
}

withDefaults(defineProps<Props>(), { columns: 3 })

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
	<fieldset
		:disabled="disabled"
		:class="[
			'grid gap-3',
			columns === 2 ? 'md:grid-cols-2' : 'grid-cols-2 md:grid-cols-3',
		]"
		role="radiogroup"
		:aria-label="label"
	>
		<button
			v-for="option in options"
			:key="option.value"
			type="button"
			role="radio"
			:aria-checked="modelValue === option.value"
			@click="emit('update:modelValue', option.value)"
		>
			<slot name="icon" :option="option" />
			<span class="min-w-0">
				<span class="block truncate text-base-medium text-ink-gray-8">
					{{ option.label }}
				</span>
				<span
					v-if="option.description"
					class="block truncate text-p-xs text-ink-gray-5"
				>
					{{ option.description }}
				</span>
			</span>
		</button>
	</fieldset>
</template>

<style scoped>
button {
	@apply flex w-full items-center gap-3 rounded-6 border border-outline-gray-2 px-3 py-2 text-start transition-colors;

	&:hover {
		@apply bg-surface-gray-2;
	}

	&[aria-checked="true"] {
		@apply border-outline-gray-6;
	}

	&:focus-visible {
		@apply outline-none ring-1 ring-outline-gray-4;
	}

	&:disabled {
		@apply cursor-not-allowed opacity-50;
	}
}
</style>
