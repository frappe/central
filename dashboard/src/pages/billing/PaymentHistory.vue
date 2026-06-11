<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Badge, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import ListToolbar from '@/components/ListToolbar.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { money } from '@/utils/money'
import { paymentTheme } from '@/utils/status'

// Read-only record of every charge attempt — including the failed dunning
// retries that explain why a card-on-file team can still be past_due/suspended.
const router = useRouter()
const { currentTeam } = useTeam()

const attempts = useCall({
  url: m(API.paymentAttempts),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

const search = ref('')
const status = ref('all')
const tabs = [
  { label: 'All', value: 'all' },
  { label: 'Succeeded', value: 'succeeded' },
  { label: 'Failed', value: 'failed' },
]
const rows = computed(() => {
  let list = attempts.data || []
  if (status.value !== 'all') {
    list = list.filter((a) => String(a.status).toLowerCase() === status.value)
  }
  const q = search.value.trim().toLowerCase()
  if (q) {
    list = list.filter(
      (a) =>
        (a.invoice || '').toLowerCase().includes(q) ||
        (a.gateway || '').toLowerCase().includes(q) ||
        (a.gateway_transaction_id || '').toLowerCase().includes(q),
    )
  }
  return list
})

function openInvoice(a) {
  if (a.invoice) router.push({ name: 'Invoices' })
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Billing' }, { label: 'Payment History' }]" />

    <div class="flex min-h-0 flex-1 flex-col">
      <ListToolbar
        v-model:search="search"
        v-model:status="status"
        :tabs="tabs"
        placeholder="Search by invoice, gateway, txn…"
      />

      <div class="min-h-0 flex-1 overflow-y-auto">
        <div v-if="attempts.loading && !attempts.data" class="space-y-3 p-4">
          <LoadingText :lines="6" />
        </div>
        <div v-else-if="!rows.length" class="px-4 py-12 text-center text-p-sm text-ink-gray-5">
          No payment attempts match.
        </div>
        <ul v-else class="divide-y divide-outline-gray-1">
          <li v-for="a in rows" :key="a.name" class="px-4 py-3">
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <button
                    v-if="a.invoice"
                    class="truncate text-sm text-ink-blue-3 hover:underline"
                    @click="openInvoice(a)"
                  >
                    {{ a.invoice }}
                  </button>
                  <span v-else class="text-sm text-ink-gray-8">Top-up / adjustment</span>
                  <Badge v-if="a.retry_number" theme="gray" :label="`retry #${a.retry_number}`" />
                </div>
                <p class="text-p-sm text-ink-gray-5">
                  {{ a.gateway }} · {{ a.creation }}
                  <span v-if="a.gateway_transaction_id">· {{ a.gateway_transaction_id }}</span>
                </p>
              </div>
              <div class="flex items-center gap-3">
                <span class="text-sm text-ink-gray-8">{{ money(a.amount, a.currency) }}</span>
                <Badge :theme="paymentTheme(a.status)" :label="a.status" />
              </div>
            </div>
            <p
              v-if="a.failure_reason || a.failure_code"
              class="mt-1.5 rounded bg-surface-red-1 px-2.5 py-1.5 text-p-sm text-ink-red-3"
            >
              {{ a.failure_reason || a.failure_code }}
              <span v-if="a.failure_reason && a.failure_code" class="text-ink-red-2">
                ({{ a.failure_code }})
              </span>
            </p>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
