<script setup lang="ts">
import { Button } from 'frappe-ui'

const props = defineProps<{
  kind: 'empty' | 'filtered' | 'error'
  title: string
  description?: string
}>()

defineEmits<{
  retry: []
  clear: []
}>()

const icons = {
  empty: 'lucide-inbox',
  filtered: 'lucide-search-x',
  error: 'lucide-circle-alert',
} as const
</script>

<template>
  <div class="flex min-h-64 flex-col items-center justify-center px-6 py-12 text-center">
    <div
      class="flex size-10 items-center justify-center rounded-full bg-surface-gray-2 text-ink-gray-5"
    >
      <span :class="[icons[props.kind], 'size-4']" aria-hidden="true" />
    </div>
    <p class="mt-4 text-base font-medium text-ink-gray-8">{{ title }}</p>
    <p v-if="description" class="mt-1 max-w-sm text-p-sm text-ink-gray-5">
      {{ description }}
    </p>
    <Button
      v-if="kind === 'error'"
      class="mt-4"
      label="Try again"
      icon-left="lucide-refresh-cw"
      @click="$emit('retry')"
    />
    <Button
      v-else-if="kind === 'filtered'"
      class="mt-4"
label="Clear"
      @click="$emit('clear')"
    />
    <div v-else-if="$slots.action" class="mt-4">
      <slot name="action" />
    </div>
  </div>
</template>
