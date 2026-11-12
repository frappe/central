<script setup lang="ts">
import { TextInput } from 'frappe-ui'
import { nextTick, useTemplateRef } from 'vue'

interface Props {
	placeholder: string
	label: string
}

defineProps<Props>()
const query = defineModel<string>({ required: true })

const input = useTemplateRef<{ $el?: HTMLElement }>('input')

function focus(): void {
	nextTick(() => input.value?.$el?.querySelector('input')?.focus())
}

function clear(): void {
	query.value = ''
	focus()
}

defineExpose({ focus })
</script>

<template>
	<TextInput
		ref="input"
		v-model="query"
		class="min-w-0 flex-1"
		:placeholder="placeholder"
		:aria-label="label"
	>
		<template #prefix>
			<span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" />
		</template>
		<template v-if="query" #suffix>
			<button
				type="button"
				class="flex size-4 items-center justify-center rounded-2 text-ink-gray-5 hover:bg-surface-gray-3 hover:text-ink-gray-8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
				aria-label="Clear search"
				@click="clear"
			>
				<span class="lucide-x size-3.5" aria-hidden="true" />
			</button>
		</template>
	</TextInput>
</template>
