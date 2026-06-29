<script setup lang="ts">
// Shared chrome for the consolidated Billing Overview cards (#69): a titled,
// bordered surface with an optional header action slot and a body.
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <section class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1">
    <header class="flex items-start justify-between gap-3 border-b border-outline-gray-1 px-5 py-3.5">
      <div class="min-w-0">
        <h2 class="text-base text-ink-gray-9">{{ title }}</h2>
        <p v-if="description" class="mt-0.5 text-p-sm text-ink-gray-5">{{ description }}</p>
      </div>
      <div class="shrink-0">
        <slot name="action" />
      </div>
    </header>
    <div class="px-5 py-4">
      <slot />
    </div>
  </section>
</template>
