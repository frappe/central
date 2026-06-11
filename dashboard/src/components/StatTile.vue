<script setup>
// A section surface (heading + number), not a decorative boxed card.
// Color lives only on status badges / alerts the caller slots in.
defineProps({
  label: { type: String, required: true },
  value: { type: String, default: '' },
  sub: { type: String, default: '' },
})
</script>

<template>
  <div class="rounded border border-outline-gray-1 px-4 py-3">
    <p class="text-sm text-ink-gray-5">{{ label }}</p>
    <p v-if="value" class="mt-1 text-2xl text-ink-gray-9">{{ value }}</p>
    <slot name="value" />
    <p v-if="sub" class="mt-1 text-p-sm text-ink-gray-6">{{ sub }}</p>
    <div class="mt-2"><slot /></div>
  </div>
</template>
