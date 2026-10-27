<script setup lang="ts">
import { computed } from 'vue'
import ChoiceCards from '@/components/common/ChoiceCards.vue'
import type { Template } from '@/types/serverCreation'

const props = defineProps<{
	modelValue: string
	templates: Template[]
	disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const options = computed(() =>
	props.templates.map((template) => ({
		label: template.title,
		value: template.snapshot_id,
		description: [
			template.information,
			template.os_version && `Ubuntu ${template.os_version}`,
		]
			.filter(Boolean)
			.join(' · '),
	})),
)
</script>

<template>
	<ChoiceCards
		:model-value="modelValue"
		:options="options"
		:disabled="disabled"
		:columns="2"
		label="Select a template"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<template #icon="{ option }">
			<span
				class="grid size-6 shrink-0 place-items-center rounded-4 bg-surface-gray-2 text-ink-gray-8"
				aria-hidden="true"
				>{{ option.label.charAt(0) }}</span
			>
		</template>
	</ChoiceCards>
</template>
