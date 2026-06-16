<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Button, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { money, signedMoney } from '@/utils/money'

const router = useRouter()
const { currentTeam } = useTeam()
const { canManage } = useCapabilities()
const { complete: setupComplete } = useBillingSetup()

const params = () => ({ team: currentTeam.value })
const balance = useCall({ url: m(API.creditBalance), params, refetch: true })
const ledger = useCall({ url: m(API.creditLedger), params, refetch: true })

const currency = computed(() => balance.data?.currency || 'INR')
const showTopup = ref(false)

function reloadAll() {
  balance.reload()
  ledger.reload()
}

// Credits go up on top-up/refund, down when applied to an invoice.
function isCredit(entry) {
  return Number(entry.amount) >= 0 && entry.entry_type !== 'Debit'
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Billing' }, { label: 'Credits' }]">
      <template #actions>
        <Button
          v-if="canManage"
          variant="solid"
          label="Top up"
          :disabled="!setupComplete"
          @click="showTopup = true"
        />
      </template>
    </PageHeader>

    <div class="body-container space-y-6 pb-40 pt-5">
      <div v-if="balance.loading && !balance.data" class="space-y-3">
        <LoadingText :lines="4" />
      </div>

      <template v-else>
        <div
          v-if="canManage && !setupComplete"
          class="flex items-center justify-between gap-3 rounded border border-outline-amber-2 bg-surface-amber-1 px-4 py-3"
        >
          <p class="text-p-sm text-ink-amber-3">
            Set your billing currency and address before topping up your wallet.
          </p>
          <Button variant="subtle" label="Go to Settings" @click="router.push({ name: 'Address' })" />
        </div>

        <StatTile
          label="Wallet balance"
          :value="money(balance.data?.balance ?? 0, currency)"
          sub="Applied to invoices before any card is charged"
        />

        <section class="rounded border border-outline-gray-1">
          <header class="border-b border-outline-gray-1 px-4 py-3">
            <h2 class="text-base text-ink-gray-8">Credit history</h2>
          </header>
          <div
            v-if="ledger.loading && !ledger.data"
            class="space-y-3 p-4"
          >
            <LoadingText :lines="5" />
          </div>
          <div
            v-else-if="!ledger.data?.length"
            class="px-4 py-10 text-center text-p-sm text-ink-gray-5"
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
                <p class="truncate text-sm text-ink-gray-8">
                  {{ e.note || e.entry_type }}
                </p>
                <p class="text-p-sm text-ink-gray-5">{{ e.created_at }}</p>
              </div>
              <div class="text-right">
                <p
                  class="text-sm"
                  :class="isCredit(e) ? 'text-ink-green-3' : 'text-ink-gray-8'"
                >
                  {{ signedMoney(e.amount, e.currency || currency, isCredit(e)) }}
                </p>
                <p class="text-p-sm text-ink-gray-5">
                  bal {{ money(e.running_balance, e.currency || currency) }}
                </p>
              </div>
            </li>
          </ul>
        </section>
      </template>
    </div>

    <TopupDialog v-model="showTopup" :currency="currency" @done="reloadAll" />
  </div>
</template>
