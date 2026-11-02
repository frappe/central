<script setup lang="ts">
import { computed } from 'vue'
import appsLogo from '@/assets/images/apps.svg'
import ChoiceCards from '@/components/common/ChoiceCards.vue'
import type { App } from '@/types/serverCreation'

const props = defineProps<{
	modelValue: string
	apps: App[]
	disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const logos = computed(
	() =>
		new Map(props.apps.map((app) => [app.snapshot_id, app.logo || appsLogo])),
)

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
			<img
				:src="logos.get(option.value) ?? appsLogo"
				alt=""
				class="size-6 shrink-0 object-contain"
				draggable="false"
			/>
		</template>
	</ChoiceCards>
</template>
