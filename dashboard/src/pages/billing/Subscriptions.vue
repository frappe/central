<script setup>
import { useCall } from 'frappe-ui'
import { Badge, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { standingTheme } from '@/utils/status'

// Active plan subscriptions per cluster — the intent rows the invoice line items
// are accrued from. Read-only here; plan changes happen in the plan configurator.
const { currentTeam } = useTeam()

const subscriptions = useCall({
  url: m(API.subscriptions),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Billing' }, { label: 'Subscriptions' }]" />

    <div class="body-container space-y-4 pb-40 pt-5">
      <div v-if="subscriptions.loading && !subscriptions.data" class="space-y-3">
        <LoadingText :lines="4" />
      </div>

      <div
        v-else-if="!subscriptions.data?.length"
        class="rounded border border-dashed border-outline-gray-2 px-6 py-12 text-center"
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
              {{ sub.billing_cycle || 'monthly' }}
              <span v-if="sub.start_date"> · since {{ sub.start_date }}</span>
            </p>
          </div>
          <Badge
            :theme="standingTheme(sub.account_standing)"
            :label="sub.account_standing || 'current'"
          />
        </li>
      </ul>
    </div>
  </div>
</template>
