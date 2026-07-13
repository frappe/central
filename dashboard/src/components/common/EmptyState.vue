<script setup lang="ts">
// Canonical "nothing here" state: a dashed-border card with an icon, a clear
// message, and an optional CTA in the #action slot. Used for empty list views
// and empty pages. Render the CTA only when there genuinely is one — and when
// you do, it should be the only primary action in view.
withDefaults(
  defineProps<{
    icon?: string
    title: string
    description?: string
  }>(),
  { icon: 'lucide-inbox' },
)
</script>

<template>
  <div
    class="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-outline-gray-3 px-6 py-12 text-center"
  >
    <div
      class="flex size-10 items-center justify-center rounded-lg bg-surface-gray-2 text-ink-gray-5"
    >
      <span :class="[icon, 'size-4']" aria-hidden="true" />
    </div>
    <p class="mt-4 text-base font-medium text-ink-gray-8">{{ title }}</p>
    <p v-if="description" class="mt-1 max-w-sm text-p-sm text-ink-gray-5">
      {{ description }}
    </p>
    <div v-if="$slots.action" class="mt-5">
      <slot name="action" />
    </div>
  </div>
</template>
