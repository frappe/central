<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, LoadingText } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { money, signedMoney } from '@/lib/format'
import type { CreditLedgerEntry } from '@/types/billing'

// Wallet — balance, top-up (via #67 useTopup in TopupDialog), and the credit
// ledger. Top-up is gated on a complete profile (requireSetup diverts otherwise).
const { credit, ledger, currency, reloadMoney } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const balance = computed(() => Number(credit.data?.balance ?? 0))
const loading = computed(() => credit.loading && !credit.data)

const showTopup = ref(false)
function onTopup(): void {
  if (requireSetup()) showTopup.value = true
}

// Credits go up on top-up/refund, down when applied to an invoice.
function isCredit(entry: CreditLedgerEntry): boolean {
  return Number(entry.amount) >= 0 && entry.entry_type !== 'Debit'
}
</script>

<template>
  <BillingCard title="Wallet" description="Applied to invoices before any card is charged">
    <template #action>
      <Button v-if="canManageBilling" variant="subtle" label="Add" @click="onTopup">
        <template #prefix><span class="lucide-plus size-4" aria-hidden="true" /></template>
      </Button>
    </template>

    <div v-if="loading" class="space-y-3">
      <LoadingText :lines="3" />
    </div>

    <div v-else class="space-y-4">
      <p class="text-2xl font-semibold tabular-nums text-ink-gray-9">
        {{ money(balance, currency) }}
      </p>

      <div class="rounded-lg border border-outline-gray-1">
        <header class="border-b border-outline-gray-1 px-4 py-2.5">
          <h3 class="text-p-sm font-medium text-ink-gray-7">Credit history</h3>
        </header>
        <div v-if="ledger.loading && !ledger.data" class="space-y-3 p-4">
          <LoadingText :lines="4" />
        </div>
        <div
          v-else-if="!ledger.data?.length"
          class="px-4 py-8 text-center text-p-sm text-ink-gray-5"
        >
          No credit activity yet.
        </div>
        <ul v-else class="divide-y divide-outline-gray-1">
          <li
            v-for="(e, idx) in ledger.data"
            :key="idx"
            class="flex items-center justify-between gap-3 px-4 py-3"
          >
            <div class="min-w-0">
              <p class="truncate text-sm text-ink-gray-8">{{ e.note || e.entry_type }}</p>
              <p class="text-p-sm text-ink-gray-5">{{ e.created_at }}</p>
            </div>
            <div class="text-right">
              <p class="text-sm" :class="isCredit(e) ? 'text-ink-green-3' : 'text-ink-gray-8'">
                {{ signedMoney(e.amount, e.currency || currency, isCredit(e)) }}
              </p>
              <p class="text-p-sm text-ink-gray-5">
                bal {{ money(e.running_balance, e.currency || currency) }}
              </p>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <TopupDialog v-model="showTopup" :currency="currency" @done="reloadMoney" />
  </BillingCard>
</template>
