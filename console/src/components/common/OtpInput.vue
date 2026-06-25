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
  nextTick(() => document.querySelector<HTMLInputElement>('[data-otp-input]')?.focus())
})
</script>

<template>
  <fieldset :disabled="disabled">
    <legend class="mb-2 text-sm font-medium text-ink-gray-8">{{ label }}</legend>
    <PinInputRoot
      v-model="digits"
      type="number"
      otp
      class="flex gap-2"
      :disabled="disabled"
      @complete="complete"
    >
      <PinInputInput
        v-for="index in length"
        :key="index"
        :index="index - 1"
        data-otp-input
        :aria-label="`${label} digit ${index}`"
        class="h-10 min-w-0 flex-1 rounded border border-outline-gray-2 bg-surface-base text-center text-lg font-medium text-ink-gray-9 shadow-sm outline-none transition-colors hover:border-outline-gray-3 focus:border-outline-gray-4 focus:ring-2 focus:ring-outline-gray-1 disabled:cursor-not-allowed disabled:opacity-50"
      />
    </PinInputRoot>
  </fieldset>
</template>
