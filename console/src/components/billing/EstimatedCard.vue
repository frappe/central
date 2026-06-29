<script setup lang="ts">
import { computed } from 'vue'
import { LoadingText } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { money } from '@/lib/format'
import { billingPeriod } from '@/lib/date'

// Estimated this cycle — the cost composition that adds up to the projected bill
// (usage + tax = estimated), plus the credit position (available / required) and
// the low-wallet alert. Reads get_forecast (+ get_team_overview for currency).
const { forecast, credit, currency } = useBillingOverview()

const loading = computed(() => forecast.loading && !forecast.data)
const fc = computed(() => forecast.data)
const cycleLabel = computed(() =>
  fc.value?.period_start ? billingPeriod(fc.value.period_start, fc.value.period_end) : '',
)

const currentUsage = computed(() => Number(fc.value?.subtotal ?? 0))
const taxAmount = computed(() => Number(fc.value?.tax_amount ?? 0))
const taxLabel = computed(() => fc.value?.tax_type || 'Tax')
const projected = computed(() => Number(fc.value?.projected_total ?? 0))
const creditBalance = computed(() =>
  Number(credit.data?.balance ?? fc.value?.credit_balance ?? 0),
)
const estRequired = computed(() =>
  Number(fc.value?.shortfall ?? Math.max(0, projected.value - creditBalance.value)),
)
const daysRemaining = computed(() => fc.value?.days_remaining ?? null)

// Warn whenever the projected bill is within 20% of (or above) the wallet, so the
// team can top up in time. Applies to any team holding credits.
const eightyPctAlert = computed(
  () => creditBalance.value > 0 && projected.value >= 0.8 * creditBalance.value,
)

// Usage grouped by plan/line, largest first.
const byProject = computed(() => {
  const items = fc.value?.line_items ?? []
  const groups = new Map<string, { label: string; amount: number }>()
  for (const li of items) {
    const key = li.plan || li.description || 'Usage'
    const g = groups.get(key) || { label: li.description || key, amount: 0 }
    g.amount += Number(li.amount || 0)
    groups.set(key, g)
  }
  return [...groups.values()].sort((a, b) => b.amount - a.amount)
})
</script>

<template>
  <BillingCard title="Estimated this cycle">
    <template #action>
      <span v-if="cycleLabel" class="text-p-sm text-ink-gray-5">{{ cycleLabel }}</span>
    </template>

    <div v-if="loading" class="space-y-3">
      <LoadingText :lines="5" />
    </div>

    <div v-else class="space-y-4">
      <div
        v-if="eightyPctAlert"
        class="rounded border border-outline-amber-1 bg-surface-amber-1 px-4 py-3 text-p-sm text-ink-amber-3"
      >
        Your projected usage ({{ money(projected, currency) }}) is nearing your wallet balance
        ({{ money(creditBalance, currency) }}). Consider topping up to avoid interruption.
      </div>

      <div class="grid gap-4 lg:grid-cols-[1fr_auto]">
        <!-- Cost breakdown: usage + tax = estimated month's cost -->
        <dl class="space-y-3 rounded-lg border border-outline-gray-2 px-5 py-4 text-sm">
          <div class="flex justify-between text-ink-gray-6">
            <dt>Current usage</dt>
            <dd class="tabular-nums text-ink-gray-8">{{ money(currentUsage, currency) }}</dd>
          </div>
          <div v-if="taxAmount > 0" class="flex justify-between text-ink-gray-6">
            <dt>{{ taxLabel }}</dt>
            <dd class="tabular-nums text-ink-gray-8">{{ money(taxAmount, currency) }}</dd>
          </div>
          <div
            class="flex justify-between border-t border-outline-gray-1 pt-3 text-base text-ink-gray-9"
          >
            <dt>
              Estimated month's cost
              <span v-if="daysRemaining != null" class="text-p-sm text-ink-gray-5">
                · {{ daysRemaining }} days left
              </span>
            </dt>
            <dd class="tabular-nums">{{ money(projected, currency) }}</dd>
          </div>
        </dl>

        <!-- Credit position -->
        <div class="grid grid-cols-2 gap-4 lg:w-[26rem]">
          <div class="grid place-items-center rounded-lg bg-surface-gray-2 px-4 py-6 text-center">
            <p class="text-p-sm text-ink-gray-6">Credits available</p>
            <p class="mt-1 text-2xl font-semibold tabular-nums text-ink-gray-9">
              {{ money(creditBalance, currency) }}
            </p>
          </div>
          <div class="grid place-items-center rounded-lg bg-surface-gray-2 px-4 py-6 text-center">
            <p class="text-p-sm text-ink-gray-6">Est. credits required</p>
            <p
              class="mt-1 text-2xl font-semibold tabular-nums"
              :class="estRequired > 0 ? 'text-ink-amber-3' : 'text-ink-green-3'"
            >
              {{ money(estRequired, currency) }}
            </p>
          </div>
        </div>
      </div>

      <!-- Usage by line -->
      <div v-if="byProject.length" class="rounded-lg border border-outline-gray-1">
        <header class="border-b border-outline-gray-1 px-4 py-2.5">
          <h3 class="text-p-sm font-medium text-ink-gray-7">Usage breakdown</h3>
        </header>
        <ul class="divide-y divide-outline-gray-1">
          <li
            v-for="p in byProject"
            :key="p.label"
            class="flex items-center justify-between gap-3 px-4 py-2.5"
          >
            <p class="truncate text-sm text-ink-gray-8">{{ p.label }}</p>
            <span class="shrink-0 text-sm tabular-nums text-ink-gray-7">
              {{ money(p.amount, currency) }}
            </span>
          </li>
        </ul>
      </div>
    </div>
  </BillingCard>
</template>
