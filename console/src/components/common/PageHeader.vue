<script setup lang="ts">
// Standard page header: title (+ optional subtitle) on the left, page #actions
// plus the global notification bell on the right. Sits above the scrolling page
// body inside a `flex h-full flex-col` page — so the bell is reachable everywhere.
import NotificationBell from '@/components/notifications/NotificationBell.vue'

defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header
    class="flex items-center justify-between gap-3 border-b border-outline-gray-1 px-4 py-3 sm:px-6"
  >
    <div class="min-w-0">
      <h1 class="truncate text-lg font-semibold text-ink-gray-9">{{ title }}</h1>
      <p v-if="subtitle" class="truncate text-p-sm text-ink-gray-5">{{ subtitle }}</p>
    </div>
    <div class="flex shrink-0 items-center gap-2">
      <slot name="actions" />
      <NotificationBell />
    </div>
  </header>
</template>
