<script setup lang="ts">
import { Badge, LoadingText } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { standingTheme } from '@/lib/status'

// Subscriptions — the active per-server plan rows the invoice line items accrue
// from. Read-only here; plan changes happen in the plan configurator.
const { subscriptions } = useBillingOverview()
</script>

<template>
  <BillingCard title="Subscriptions">
    <div v-if="subscriptions.loading && !subscriptions.data" class="space-y-3">
      <LoadingText :lines="3" />
    </div>

    <div
      v-else-if="!subscriptions.data?.length"
      class="rounded border border-dashed border-outline-gray-2 px-6 py-8 text-center"
    >
      <p class="text-p-base text-ink-gray-6">No active subscriptions.</p>
    </div>

    <ul v-else class="space-y-2">
      <li
        v-for="sub in subscriptions.data"
        :key="sub.name"
        class="flex items-center justify-between gap-3 rounded border border-outline-gray-1 px-4 py-3"
      >
        <div class="min-w-0">
          <p class="truncate text-sm text-ink-gray-8">{{ sub.plan || sub.name }}</p>
          <p class="text-p-sm text-ink-gray-5">
            <span v-if="sub.cluster">{{ sub.cluster }} · </span>
            {{ sub.billing_cycle || 'Monthly' }}
            <span v-if="sub.start_date"> · since {{ sub.start_date }}</span>
          </p>
        </div>
        <Badge
          :theme="standingTheme(sub.account_standing)"
          :label="sub.account_standing || 'Current'"
        />
      </li>
    </ul>
  </BillingCard>
</template>
