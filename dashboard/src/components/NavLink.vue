<script setup>
import { RouterLink } from 'vue-router'

defineProps({
  to: { type: String, required: true },
  label: { type: String, required: true },
  icon: { type: String, default: '' },
  // Locked until billing setup is complete — shown greyed with a lock, not a link.
  disabled: { type: Boolean, default: false },
})
</script>

<template>
  <div
    v-if="disabled"
    class="flex cursor-not-allowed items-center gap-2 rounded px-2 py-1.5 text-base text-ink-gray-4"
    title="Complete billing setup to unlock"
    aria-disabled="true"
  >
    <span v-if="icon" :class="[icon, 'size-4 shrink-0']" aria-hidden="true" />
    <span class="truncate">{{ label }}</span>
  </div>
  <RouterLink
    v-else
    :to="to"
    class="flex items-center gap-2 rounded px-2 py-1.5 text-base text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
    exact-active-class="bg-surface-gray-3 text-ink-gray-9 hover:bg-surface-gray-3"
  >
    <span v-if="icon" :class="[icon, 'size-4 shrink-0']" aria-hidden="true" />
    <span class="truncate">{{ label }}</span>
  </RouterLink>
</template>
