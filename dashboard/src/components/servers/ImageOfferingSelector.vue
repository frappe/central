<script setup lang="ts">
import pilotLogo from '@/assets/images/pilot-logo.svg'
import ubuntuLogo from '@/assets/images/ubuntu.svg'
import ChoiceCards from '@/components/common/ChoiceCards.vue'

interface ImageChoice {
	label: string
	value: string
	logo: string | null
}

defineProps<{
	modelValue: string
	options: ImageChoice[]
	disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

// Offerings Central knows by name ship with a logo even when the catalog has none.
const defaultLogos: Record<string, string> = {
	pilot: pilotLogo,
	ubuntu: ubuntuLogo,
}

function logoFor(option: ImageChoice): string | null {
	return option.logo || defaultLogos[option.value] || null
}
</script>

<template>
	<div>
		<ChoiceCards
			:model-value="modelValue"
			:options="options"
			:disabled="disabled"
			label="Select an image"
			@update:model-value="emit('update:modelValue', $event)"
		>
			<template #icon="{ option }">
				<img
					v-if="logoFor(option as ImageChoice)"
					:src="logoFor(option as ImageChoice) ?? ''"
					alt=""
					class="size-7 object-contain"
					draggable="false"
				/>
				<span
					v-else
					class="grid size-7 place-items-center rounded-full bg-surface-gray-3 text-ink-gray-8"
					aria-hidden="true"
					>{{ option.label.charAt(0) }}</span
				>
			</template>
		</ChoiceCards>
		<p v-if="!options.length" class="text-p-sm text-ink-gray-5">
			No images are configured.
		</p>
	</div>
</template>
