<script setup lang="ts">
import { computed } from 'vue'
import { LoadingText } from 'frappe-ui'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { money } from '@/lib/format'

// Wallet — compact summary card. The chevron opens the wallet-history slide-over
// (balance, auto-recharge, ledger, add credit), owned by the page.
defineProps<{ active?: boolean }>()
defineEmits<{ open: [] }>()
const { credit, forecast, currency } = useBillingOverview()

const balance = computed(() => Number(credit.data?.balance ?? 0))
const projected = computed(() => Number(forecast.data?.projected_total ?? 0))
const loading = computed(() => credit.loading && !credit.data)
// Warn when the wallet can't cover the projected bill (prepaid teams top up).
const shortfall = computed(() => projected.value > 0 && balance.value < projected.value)
</script>

<template>
  <button
    type="button"
    class="flex flex-col rounded-lg border bg-surface-elevation-1 p-5 text-left transition-colors"
    :class="active ? 'border-outline-gray-4 ring-1 ring-outline-gray-3' : 'border-outline-gray-2 hover:border-outline-gray-3'"
    @click="$emit('open')"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="flex items-center gap-1 text-p-sm text-ink-gray-5">
        Wallet
        <span class="lucide-info size-3.5 text-ink-gray-4" aria-hidden="true" />
      </span>
      <span
        class="grid size-6 place-items-center rounded-full border border-outline-gray-2 text-ink-gray-6"
      >
        <span class="lucide-chevron-right size-4" aria-hidden="true" />
      </span>
    </div>

    <div v-if="loading" class="mt-2 w-32">
      <LoadingText :lines="1" />
    </div>
    <template v-else>
      <p class="mt-1 text-2xl font-semibold tabular-nums text-ink-gray-9">
        {{ money(balance, currency) }}
      </p>
      <p v-if="shortfall" class="mt-1 flex items-center gap-1.5 text-p-sm text-ink-red-3">
        <span class="lucide-triangle-alert size-3.5" aria-hidden="true" />
        Won't cover the {{ money(projected, currency) }} invoice
      </p>
    </template>
  </button>
</template>
