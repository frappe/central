<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Switch, LoadingText } from 'frappe-ui'
import TopupDialog from '@/components/TopupDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { money, signedMoney } from '@/lib/format'
import { infoToast } from '@/lib/toast'
import type { CreditLedgerEntry } from '@/types/billing'

// Wallet history — a docked side panel (like the invoice detail tray), opened
// from the compact Wallet card. Balance header, auto-recharge toggle, the credit
// ledger, and Add credit (TopupDialog → #67). The page owns whether it's mounted;
// the close button clears that.
const open = defineModel<boolean>({ default: false })
const { credit, ledger, currency, reloadMoney } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const balance = computed(() => Number(credit.data?.balance ?? 0))

// GROUNDING GAP (#69): no auto-recharge endpoint yet. The toggle is rendered to
// match the design but is inert until one lands.
const autoRecharge = ref(false)
function onAutoRecharge(): void {
  autoRecharge.value = false
  infoToast('Auto-recharge isn’t available yet.')
}

const showTopup = ref(false)
function onAddCredit(): void {
  if (requireSetup()) showTopup.value = true
}

function isCredit(entry: CreditLedgerEntry): boolean {
  return Number(entry.amount) >= 0 && entry.entry_type !== 'Debit'
}
</script>

<template>
  <aside
    class="flex w-full shrink-0 flex-col overflow-hidden border-outline-gray-1 bg-surface-elevation-1 sm:w-[30rem] sm:border-l"
  >
    <header class="flex items-start justify-between gap-3 border-b border-outline-gray-1 px-5 py-4">
      <div>
        <h2 class="text-base font-medium text-ink-gray-9">Wallet history</h2>
        <p class="mt-0.5 text-p-sm text-ink-gray-5">Balance {{ money(balance, currency) }}</p>
      </div>
      <button
        class="grid size-6 place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
        aria-label="Close wallet history"
        @click="open = false"
      >
        <span class="lucide-x size-4" aria-hidden="true" />
      </button>
    </header>

    <!-- Auto-recharge -->
    <div class="flex items-start justify-between gap-3 border-b border-outline-gray-1 px-5 py-4">
      <div class="min-w-0">
        <p class="text-sm text-ink-gray-8">Auto-recharge</p>
        <p class="text-p-sm text-ink-gray-5">Top up automatically when your wallet runs low.</p>
      </div>
      <Switch
        :model-value="autoRecharge"
        :disabled="!canManageBilling"
        @update:model-value="onAutoRecharge"
      />
    </div>

    <!-- Ledger -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div v-if="ledger.loading && !ledger.data" class="space-y-3 p-5">
        <LoadingText :lines="5" />
      </div>
      <div v-else-if="!ledger.data?.length" class="px-5 py-12 text-center text-p-sm text-ink-gray-5">
        No credit activity yet.
      </div>
      <ul v-else class="divide-y divide-outline-gray-1">
        <li v-for="(e, idx) in ledger.data" :key="idx" class="flex items-center gap-3 px-5 py-3">
          <span
            class="grid size-8 shrink-0 place-items-center rounded-full"
            :class="isCredit(e) ? 'bg-surface-green-2' : 'bg-surface-gray-2'"
          >
            <span
              class="size-4"
              :class="
                isCredit(e)
                  ? 'lucide-arrow-down-left text-ink-green-3'
                  : 'lucide-arrow-up-right text-ink-gray-6'
              "
              aria-hidden="true"
            />
          </span>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm text-ink-gray-8">{{ e.note || e.entry_type }}</p>
            <p class="text-p-sm text-ink-gray-5">{{ e.created_at }}</p>
          </div>
          <span
            class="shrink-0 text-sm tabular-nums"
            :class="isCredit(e) ? 'text-ink-green-3' : 'text-ink-gray-8'"
          >
            {{ signedMoney(e.amount, e.currency || currency, isCredit(e)) }}
          </span>
        </li>
      </ul>
    </div>

    <!-- Add credit -->
    <footer v-if="canManageBilling" class="border-t border-outline-gray-1 px-5 py-4">
      <Button variant="solid" theme="gray" label="Add credit" class="w-full" @click="onAddCredit">
        <template #prefix><span class="lucide-plus size-4" aria-hidden="true" /></template>
      </Button>
    </footer>

    <TopupDialog v-model="showTopup" :currency="currency" @done="reloadMoney" />
  </aside>
</template>
