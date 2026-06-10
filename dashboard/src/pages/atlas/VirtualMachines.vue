<script setup>
import PageHeader from '@/components/PageHeader.vue'
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Atlas' }, { label: 'Virtual Machines' }]" />
    <div class="body-container pt-5 pb-40">
      <p class="text-p-base text-ink-gray-5">Virtual Machines — coming up.</p>
    </div>
  </div>
</template>
