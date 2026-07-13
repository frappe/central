<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Tooltip, LoadingText } from 'frappe-ui'
import TopupDialog from '@/components/TopupDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { money } from '@/lib/format'

// Wallet — the FC v2 prototype's funding card: balance, a one-line coverage
// verdict, and (once there's a method to charge) the funding actions. The chevron
// / title open the wallet-history slide-over the page owns; Add credit tops up
// right here.
defineProps<{ active?: boolean }>()
defineEmits<{ open: [] }>()
const { credit, forecast, methods, currency, reloadMoney } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const balance = computed(() => Number(credit.data?.balance ?? 0))
const projected = computed(() => Number(forecast.data?.projected_total ?? 0))
const loading = computed(() => credit.loading && !credit.data)

// Coverage verdict, mirroring the prototype's three states. The wallet is prepaid
// and a working card covers any shortfall, so "at risk" only when the balance is
// short AND nothing can be charged behind it.
const hasMethod = computed(() => (methods.data?.length ?? 0) > 0)
const hasWorkingMethod = computed(() => (methods.data ?? []).some((m) => m.status === 'Active'))
const short = computed(() => projected.value > 0 && balance.value < projected.value)
const atRisk = computed(() => short.value && !hasWorkingMethod.value)

const showTopup = ref(false)
function onAddCredit(): void {
  if (requireSetup()) showTopup.value = true
}
</script>

<template>
  <div
    class="flex flex-col rounded-xl border bg-surface-elevation-1 p-5 transition-colors"
    :class="active ? 'border-outline-gray-4 ring-1 ring-outline-gray-4' : 'border-outline-gray-2'"
  >
    <div class="flex h-6 items-center justify-between gap-2">
      <span class="flex items-center gap-1">
        <button
          type="button"
          class="text-p-sm text-ink-gray-5 transition-colors hover:text-ink-gray-7"
          @click="$emit('open')"
        >
          Wallet
        </button>
        <Tooltip text="Applied to your invoice first, before any card is charged.">
          <span class="lucide-info size-3.5 text-ink-gray-4" aria-hidden="true" />
        </Tooltip>
      </span>
      <button
        type="button"
        class="grid size-6 place-items-center rounded text-ink-gray-4 hover:bg-surface-gray-2 hover:text-ink-gray-6"
        aria-label="Open wallet history"
        @click="$emit('open')"
      >
        <span class="lucide-chevron-right size-4" aria-hidden="true" />
      </button>
    </div>

    <div v-if="loading" class="mt-2 w-32">
      <LoadingText :lines="1" />
    </div>
    <template v-else>
      <p class="mt-1.5 text-2xl font-semibold tabular-nums text-ink-gray-9">
        {{ money(balance, currency) }}
      </p>
      <!-- Coverage verdict — always the third line -->
      <p v-if="atRisk" class="mt-1.5 flex items-center gap-1.5 text-p-sm text-ink-red-3">
        <span class="lucide-triangle-alert size-3.5 shrink-0" aria-hidden="true" />
        Insufficient balance
      </p>
      <p v-else-if="short" class="mt-1.5 flex items-center gap-1.5 text-p-sm text-ink-gray-5">
        <span class="lucide-credit-card size-3.5 shrink-0 text-ink-gray-4" aria-hidden="true" />
        Card covers the rest
      </p>
      <p v-else class="mt-1.5 text-p-sm text-ink-gray-5">Covers this invoice</p>

      <!-- Funding actions, once there's a method to charge. -->
      <div
        v-if="hasMethod && canManageBilling"
        class="mt-auto flex items-center justify-between gap-2 pt-4"
      >
        <Button
          variant="ghost"
          size="sm"
          label="Auto-recharge off"
          class="-ml-2"
          @click="$emit('open')"
        >
          <template #prefix><span class="lucide-zap size-4" aria-hidden="true" /></template>
        </Button>
        <Button variant="subtle" size="sm" label="Add credit" @click="onAddCredit">
          <template #prefix><span class="lucide-plus size-4" aria-hidden="true" /></template>
        </Button>
      </div>
    </template>

    <TopupDialog v-model="showTopup" :currency="currency" @done="reloadMoney" />
  </div>
</template>
