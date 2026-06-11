<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Badge, Button, Progress, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { money } from '@/utils/money'
import { standingTheme, invoiceTheme } from '@/utils/status'

const router = useRouter()
const { currentTeam } = useTeam()
const { canManage } = useCapabilities()

const params = () => ({ team: currentTeam.value })
const overview = useCall({ url: m(API.teamOverview), params, refetch: true })
const settings = useCall({ url: m(API.billingSettings), params, refetch: true })
const forecast = useCall({ url: m(API.forecast), params, refetch: true })
const credit = useCall({ url: m(API.creditBalance), params, refetch: true })
const invoices = useCall({ url: m(API.invoices), params, refetch: true })

const loading = computed(
  () => overview.loading && !overview.data,
)

// ── Mode-dependent headline ──────────────────────────────────────────────
const isPrepaid = computed(() => settings.data?.billing_mode === 'Prepaid')
const currency = computed(() => overview.data?.currency || forecast.data?.currency || 'INR')

const openInvoices = computed(() =>
  (invoices.data || []).filter((i) =>
    ['unpaid', 'overdue', 'open'].includes(String(i.status).toLowerCase()),
  ),
)

// Postpaid headline: total still owed across open invoices (single currency per team).
const outstanding = computed(() =>
  openInvoices.value.reduce(
    (sum, i) => sum + (Number(i.total) - Number(i.amount_paid || 0)),
    0,
  ),
)

const walletBalance = computed(() => Number(credit.data?.balance ?? 0))

// Prepaid 80% alert: projected month-end bill is closing on the wallet.
const projected = computed(() => Number(forecast.data?.projected_total ?? 0))
const eightyPctAlert = computed(
  () => isPrepaid.value && walletBalance.value > 0 && projected.value >= 0.8 * walletBalance.value,
)
const forecastPct = computed(() => {
  const denom = isPrepaid.value ? walletBalance.value : projected.value
  if (!denom) return 0
  return Math.min(100, Math.round((projected.value / denom) * 100))
})

const standing = computed(() => overview.data?.standing || 'current')

const showTopup = ref(false)
function goToInvoices() {
  router.push({ name: 'Invoices' })
}
function onToppedUp() {
  credit.reload?.()
  forecast.reload?.()
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Billing' }, { label: 'Overview' }]">
      <template #actions>
        <Button
          v-if="canManage && isPrepaid"
          variant="solid"
          label="Top up"
          @click="showTopup = true"
        />
        <Button
          v-else-if="canManage"
          variant="solid"
          label="Pay now"
          :disabled="outstanding <= 0"
          @click="goToInvoices"
        />
      </template>
    </PageHeader>

    <div class="body-container space-y-6 pb-40 pt-5">
      <div v-if="loading" class="space-y-3">
        <LoadingText :lines="6" />
      </div>

      <template v-else>
        <!-- Prepaid spend alert -->
        <div
          v-if="eightyPctAlert"
          class="rounded border border-outline-amber-1 bg-surface-amber-1 px-4 py-3 text-p-sm text-ink-amber-3"
        >
          Your projected month-end usage ({{ money(projected, currency) }}) is nearing your
          wallet balance ({{ money(walletBalance, currency) }}). Consider topping up to avoid
          interruption.
        </div>

        <!-- Headline tiles -->
        <div class="grid gap-4 sm:grid-cols-3">
          <StatTile
            v-if="isPrepaid"
            label="Wallet balance"
            :value="money(walletBalance, currency)"
            :sub="`${forecast.data?.days_remaining ?? 0} days left this cycle`"
          />
          <StatTile
            v-else
            label="Amount outstanding"
            :value="money(outstanding, currency)"
            :sub="openInvoices.length ? `${openInvoices.length} open invoice(s)` : 'All settled'"
          />

          <StatTile label="Projected this month">
            <template #value>
              <p class="mt-1 text-2xl text-ink-gray-9">{{ money(projected, currency) }}</p>
            </template>
            <Progress :value="forecastPct" size="sm" />
          </StatTile>

          <StatTile label="Account standing">
            <template #value>
              <div class="mt-2">
                <Badge :theme="standingTheme(standing)" :label="standing" size="lg" />
              </div>
            </template>
            <p class="text-p-sm text-ink-gray-5">
              Tier {{ overview.data?.tier || '—' }} · max spend
              {{ money(overview.data?.max_spend ?? 0, currency) }}
            </p>
          </StatTile>
        </div>

        <!-- Recent invoices -->
        <section class="rounded border border-outline-gray-1">
          <header class="flex items-center justify-between border-b border-outline-gray-1 px-4 py-3">
            <h2 class="text-base text-ink-gray-8">Recent invoices</h2>
            <Button variant="ghost" label="View all" @click="goToInvoices" />
          </header>
          <div v-if="!invoices.data?.length" class="px-4 py-8 text-center text-p-sm text-ink-gray-5">
            No invoices yet.
          </div>
          <ul v-else class="divide-y divide-outline-gray-1">
            <li
              v-for="inv in invoices.data.slice(0, 5)"
              :key="inv.name"
              class="flex items-center justify-between gap-3 px-4 py-3"
            >
              <div class="min-w-0">
                <p class="truncate text-sm text-ink-gray-8">{{ inv.name }}</p>
                <p class="text-p-sm text-ink-gray-5">
                  {{ inv.period_start }} → {{ inv.period_end }}
                </p>
              </div>
              <div class="flex items-center gap-3">
                <span class="text-sm text-ink-gray-7">{{ money(inv.total, inv.currency) }}</span>
                <Badge :theme="invoiceTheme(inv.status)" :label="inv.status" />
              </div>
            </li>
          </ul>
        </section>
      </template>
    </div>

    <TopupDialog v-model="showTopup" :currency="currency" @done="onToppedUp" />
  </div>
</template>
