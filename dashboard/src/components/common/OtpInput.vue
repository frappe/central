<script setup lang="ts">
import { computed, nextTick, onMounted } from 'vue'
import { PinInputInput, PinInputRoot } from 'reka-ui'

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

const digits = computed({
	get: () => props.modelValue.split('').slice(0, props.length).map(Number),
	set: (value: number[]) => emit('update:modelValue', value.join('')),
})

function complete(value: number[]) {
	emit('complete', value.join(''))
}

onMounted(() => {
	if (!props.autofocus) return
	nextTick(() =>
		document.querySelector<HTMLInputElement>('[data-otp-input]')?.focus(),
	)
})
</script>

<template>
	<fieldset class="w-full space-y-1.5" :disabled="disabled">
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
				class="h-11 w-full min-w-0 rounded border border-outline-gray-2 bg-surface-base text-center text-lg font-medium text-ink-gray-8 transition-colors outline-none [appearance:textfield] hover:border-outline-gray-3 hover:shadow-sm focus:border-outline-gray-4 focus:shadow-sm focus:ring-0 disabled:cursor-not-allowed disabled:border-outline-gray-2 disabled:bg-surface-gray-1 disabled:text-ink-gray-5 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
			/>
		</PinInputRoot>
	</fieldset>
</template>
