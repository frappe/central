<script setup>
import { Breadcrumbs } from 'frappe-ui'

// Standard 48px sticky page header: breadcrumbs left, actions slot right.
defineProps({
  items: { type: Array, default: () => [] },
})
</script>

<template>
  <header
    class="sticky top-0 z-10 flex min-h-12 items-center justify-between gap-2 border-b border-outline-gray-1 bg-surface-white px-3 sm:px-5"
  >
    <Breadcrumbs :items="items" />
    <div class="flex items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
