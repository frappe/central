<script setup lang="ts">
import frappeCloudLogo from '@/assets/frappe-cloud-logo.svg'

withDefaults(
  defineProps<{
    step?: number
    steps?: number
    showProgress?: boolean
  }>(),
  {
    step: 1,
    steps: 4,
    showProgress: false,
  },
)
</script>

<template>
  <main class="flex min-h-screen justify-center bg-surface-base px-4 pb-12 pt-12 sm:pt-16">
    <section class="w-full max-w-[384px]">
      <header class="mb-8 flex items-center justify-center gap-2">
        <img :src="frappeCloudLogo" alt="Frappe Cloud Logo" class="h-8 w-8 rounded-4 object-contain" />
        <span class="text-xl font-semibold text-ink-gray-9">Frappe Cloud</span>
      </header>

      <div v-if="showProgress" class="mb-12 flex gap-2" aria-label="Signup progress">
        <span
          v-for="index in steps"
          :key="index"
          class="h-1 flex-1 rounded"
          :class="index <= step ? 'bg-surface-gray-6' : 'bg-surface-gray-3'"
        />
      </div>

      <slot />
    </section>
  </main>
</template>
