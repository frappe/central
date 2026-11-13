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
	props.apps.map((app) => ({ label: app.title, value: app.snapshot_id })),
)

const selectedApp = computed(() =>
	props.apps.find((item) => item.snapshot_id === props.modelValue),
)

const selectedDescription = computed(() =>
	[
		selectedApp.value?.information,
		selectedApp.value?.os_version && `Ubuntu ${selectedApp.value.os_version}`,
	]
		.filter(Boolean)
		.join(' · '),
)
</script>

<template>
	<ChoiceCards
		:model-value="modelValue"
		:options="options"
		:disabled="disabled"
		label="Select an app"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<template #icon="{ option }">
			<img
				:src="logos.get(option.value) ?? appsLogo"
				alt=""
				class="size-6 shrink-0 object-contain"
				:class="{
					'rounded-4 bg-surface-gray-2 p-1': logos.get(option.value) !== appsLogo,
				}"
				draggable="false"
			/>
		</template>
	</ChoiceCards>

	<p v-if="selectedDescription" class="text-p-sm text-ink-gray-5">
		{{ selectedDescription }}
	</p>
	<p v-if="selectedApp?.documentation" class="text-p-sm">
		<a
			:href="selectedApp.documentation"
			target="_blank"
			rel="noopener"
			class="text-p-sm-medium text-ink-gray-8 underline"
			>Read the {{ selectedApp.title }} guide</a
		>
	</p>
</template>
