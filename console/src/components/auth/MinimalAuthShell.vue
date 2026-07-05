<script setup lang="ts">
import { ToastProvider } from 'frappe-ui'
import frappeCloudLogo from '@/assets/frappe-cloud-logo.svg'
</script>

<template>
  <main class="flex min-h-screen flex-col bg-surface-white px-4">
    <ToastProvider />
    <section class="enter-rise mx-auto w-full max-w-[391px] pt-[16vh]">
      <slot />
    </section>

    <footer class="enter-rise mt-auto flex items-center justify-center gap-2 pb-10" style="--enter-delay: 120ms">
      <img :src="frappeCloudLogo" alt="" class="h-6 w-6" />
      <span class="text-sm font-semibold text-ink-gray-7">Frappe Cloud</span>
    </footer>
  </main>
</template>

<style scoped>
/* One-time screens: a subtle rise-in is worth it. Opacity-only under reduced motion. */
.enter-rise {
  animation: rise-in 300ms cubic-bezier(0.23, 1, 0.32, 1) both;
  animation-delay: var(--enter-delay, 0ms);
}

@keyframes rise-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
}

@media (prefers-reduced-motion: reduce) {
  @keyframes rise-in {
    from {
      opacity: 0;
    }
  }
}
</style>
