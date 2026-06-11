<script setup>
// Single centered empty-state when a capability is missing (or an IDOR 403 lands).
// Never show a broken dashboard.
defineProps({
  title: { type: String, default: "You don't have access" },
  message: { type: String, default: '' },
  roles: { type: String, default: 'Owner or Billing' },
})
</script>

<template>
  <div class="flex h-full flex-col items-center justify-center gap-3 px-6 py-16 text-center">
    <div class="rounded-full bg-surface-gray-2 p-3 text-ink-gray-5">
      <span class="lucide-lock size-6" aria-hidden="true" />
    </div>
    <p class="text-base text-ink-gray-7">{{ title }}</p>
    <p class="max-w-sm text-p-sm text-ink-gray-5">
      {{ message || `Ask a team admin to grant you a role that carries this access (${roles}).` }}
    </p>
  </div>
</template>
