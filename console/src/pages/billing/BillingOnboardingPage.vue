<script setup lang="ts">
// Placeholder for the billing-profile + payment-method onboarding funnel (#68).
// #66 only stands up the route the setup gate (useBillingSetup.requireSetup)
// diverts incomplete teams to; the steps land in #68.
import { useBillingSetup } from '@/composables/useBillingSetup'

const { missing } = useBillingSetup()
</script>

<template>
  <div class="mx-auto max-w-xl p-6 text-ink-gray-9">
    <h1 class="text-lg font-semibold">Complete your billing setup</h1>
    <p class="mt-2 text-p-base text-ink-gray-6">
      Add your billing profile and a payment method before moving money. The full
      flow lands in #68 — this is the gate's destination.
    </p>
    <ul v-if="missing.length" class="mt-4 list-disc pl-5 text-p-sm text-ink-gray-7">
      <li v-for="field in missing" :key="field">{{ field }}</li>
    </ul>
  </div>
</template>
