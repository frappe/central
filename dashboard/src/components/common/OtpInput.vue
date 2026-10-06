<script setup lang="ts">
import { PinInputInput, PinInputRoot } from 'reka-ui'
import { computed, nextTick, onMounted, ref } from 'vue'

const props = withDefaults(
	defineProps<{
		modelValue: string
		label?: string
		length?: number
		disabled?: boolean
		autofocus?: boolean
	}>(),
	{
		label: 'Verification code',
		length: 6,
		disabled: false,
		autofocus: false,
	},
)

const emit = defineEmits<{
	'update:modelValue': [value: string]
	complete: [value: string]
}>()

const root = ref<HTMLFieldSetElement | null>(null)

const digits = computed({
	get: () => props.modelValue.split('').slice(0, props.length).map(Number),
	set: (value: number[]) => emit('update:modelValue', value.join('')),
})

function complete(value: number[]) {
	emit('complete', value.join(''))
}

function focus() {
	root.value?.querySelector<HTMLInputElement>('[data-otp-input]')?.focus()
}

onMounted(() => {
	if (props.autofocus) nextTick(focus)
})

defineExpose({ focus })
</script>

<template>
	<fieldset ref="root" class="w-full space-y-1.5" :disabled="disabled">
		<legend class="text-p-sm-medium text-ink-gray-7">{{ label }}</legend>
		<PinInputRoot
			v-model="digits"
			type="number"
			otp
			class="grid w-full grid-cols-6 gap-2"
			:disabled="disabled"
			@complete="complete"
		>
			<PinInputInput
				v-for="index in length"
				:key="index"
				:index="index - 1"
				data-otp-input
				:aria-label="`${label} digit ${index}`"
				class="h-11 w-full min-w-0 rounded-4 border border-outline-gray-2 bg-surface-base text-center text-lg font-medium text-ink-gray-8 transition-colors outline-none [appearance:textfield] hover:border-outline-gray-3 hover:shadow-sm focus:border-outline-gray-4 focus:shadow-sm focus:ring-0 disabled:cursor-not-allowed disabled:border-outline-gray-2 disabled:bg-surface-gray-1 disabled:text-ink-gray-5 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
			/>
		</PinInputRoot>
	</fieldset>
</template>
