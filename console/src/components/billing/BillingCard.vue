<script setup lang="ts">
// Shared chrome for the consolidated Billing Overview cards (#69): a titled,
// bordered surface with an optional header action slot and a body.
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <!-- Card surface mirrors the frappe-cloud-v2 billing prototype: a rounded-xl
       hairline card with the title inline (no header divider) and a padded body. -->
  <section class="rounded-xl border border-outline-gray-2 bg-surface-elevation-1">
    <header class="flex items-start justify-between gap-3 px-5 pt-4">
      <div class="min-w-0">
        <h2 class="text-base font-semibold text-ink-gray-8">{{ title }}</h2>
        <p v-if="description" class="mt-0.5 text-p-sm text-ink-gray-5">{{ description }}</p>
      </div>
      <div class="shrink-0">
        <slot name="action" />
      </div>
    </header>
    <div class="px-5 pb-5 pt-2">
      <slot />
    </div>
  </section>
</template>
