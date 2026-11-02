<script setup lang="ts">
import { computed } from 'vue'
import ChoiceCards from '@/components/common/ChoiceCards.vue'
import type { App } from '@/types/serverCreation'

const props = defineProps<{
	modelValue: string
	apps: App[]
	disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const options = computed(() =>
	props.apps.map((app) => ({
		label: app.title,
		value: app.snapshot_id,
		description: [app.information, app.os_version && `Ubuntu ${app.os_version}`]
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
		label="Select an app"
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
