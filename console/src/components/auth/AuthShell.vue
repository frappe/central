<script setup lang="ts">
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
        <span class="grid size-8 place-items-center rounded-4 bg-surface-blue-2 text-white">
          <span class="lucide-cloud size-5" aria-hidden="true" />
        </span>
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
