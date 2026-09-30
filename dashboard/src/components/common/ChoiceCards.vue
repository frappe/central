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
			columns === 2 ? 'sm:grid-cols-2' : 'grid-cols-2 sm:grid-cols-3',
		]"
		:aria-label="label"
	>
		<button
			v-for="option in options"
			:key="option.value"
			type="button"
			:aria-pressed="modelValue === option.value"
			class="flex w-full items-center gap-3 rounded-6 border border-outline-gray-2 px-4 py-3 text-start transition-colors hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-outline-gray-4 disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:border-outline-gray-6"
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
