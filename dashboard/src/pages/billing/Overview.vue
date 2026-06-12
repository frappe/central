<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Button, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { money } from '@/utils/money'
import { billingPeriod } from '@/utils/date'

const router = useRouter()
const { currentTeam } = useTeam()
const { canManage } = useCapabilities()
const { complete: setupComplete } = useBillingSetup()

const params = () => ({ team: currentTeam.value })
const overview = useCall({ url: m(API.teamOverview), params, refetch: true })
const forecast = useCall({ url: m(API.forecast), params, refetch: true })
const credit = useCall({ url: m(API.creditBalance), params, refetch: true })
const methods = useCall({ url: m(API.paymentMethods), params, refetch: true })
const profile = useCall({ url: m(API.billingProfile), params, refetch: true })

const loading = computed(() => overview.loading && !overview.data)

// ── Cycle + credit-usage numbers ─────────────────────────────────────────
// Current cycle only; the forecast endpoint scopes itself to this month.
const fc = computed(() => forecast.data || {})
const currency = computed(() => fc.value.currency || overview.data?.currency || 'INR')
const cycleLabel = computed(() =>
  fc.value.period_start ? billingPeriod(fc.value.period_start, fc.value.period_end) : '',
)

// Left card is a cost composition that adds up to the estimated cost:
//   usage − discounts + tax = estimated month's cost.
// The credit story (available / required) lives in the two boxes on the right,
// so the breakdown stays a clean sum rather than mixing in a credit line.
const currentUsage = computed(() => Number(fc.value.subtotal ?? 0))
const discounts = computed(() => Number(fc.value.discount_total ?? 0))
const taxAmount = computed(() => Number(fc.value.tax_amount ?? 0))
const taxLabel = computed(() => fc.value.tax_type || 'Tax')
const projected = computed(() => Number(fc.value.projected_total ?? 0))
const creditBalance = computed(() => Number(credit.data?.balance ?? fc.value.credit_balance ?? 0))
const estRequired = computed(() =>
  Number(fc.value.shortfall ?? Math.max(0, projected.value - creditBalance.value)),
)

// ── Low-wallet alert ─────────────────────────────────────────────────────
// Warn whenever the projected bill is within 20% of (or above) the wallet, so
// the team can top up in time. Applies to any team holding credits.
const eightyPctAlert = computed(
  () => creditBalance.value > 0 && projected.value >= 0.8 * creditBalance.value,
)

// ── Usage by project (grouped by subscription's plan) ────────────────────
const byProject = computed(() => {
  const items = fc.value.line_items || []
  const titleByPlan = {}
  for (const li of items) if (li.plan && li.kind === 'Plan') titleByPlan[li.plan] = li.item
  const groups = new Map()
  for (const li of items) {
    const key = li.plan || li.item || 'Usage'
    const g = groups.get(key) || { label: titleByPlan[li.plan] || li.item || key, amount: 0 }
    g.amount += Number(li.amount || 0)
    groups.set(key, g)
  }
  return [...groups.values()].sort((a, b) => b.amount - a.amount)
})

// ── Account details cards ────────────────────────────────────────────────
const billingEmail = computed(() => profile.data?.email || '')
const billingAddress = computed(() => {
  const p = profile.data || {}
  return [p.address_line1, p.address_line2, p.city, p.state, p.country, p.pincode]
    .filter(Boolean)
    .join(', ')
})
const primaryMethod = computed(
  () => (methods.data || []).find((pm) => pm.is_default) || (methods.data || [])[0] || null,
)

const showTopup = ref(false)
const showAddMethod = ref(false)
function editProfile() {
  router.push({ name: 'Address' })
}
function onToppedUp() {
  credit.reload?.()
  forecast.reload?.()
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Billing' }, { label: 'Usage' }]">
      <template #actions>
        <span v-if="cycleLabel" class="hidden text-p-sm text-ink-gray-5 sm:inline">{{ cycleLabel }}</span>
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
      <div v-if="loading" class="space-y-3">
        <LoadingText :lines="6" />
      </div>

      <template v-else>
        <!-- Prepaid spend alert -->
        <div
          v-if="eightyPctAlert"
          class="rounded border border-outline-amber-1 bg-surface-amber-1 px-4 py-3 text-p-sm text-ink-amber-3"
        >
          Your projected usage ({{ money(projected, currency) }}) is nearing your wallet balance
          ({{ money(creditBalance, currency) }}). Consider topping up to avoid interruption.
        </div>

        <!-- ── Usage this cycle ───────────────────────────────────────── -->
        <section class="space-y-3">
          <h2 class="text-base text-ink-gray-9">
            <span v-if="cycleLabel">{{ cycleLabel }} ·</span> Usage
          </h2>
          <div class="grid gap-4 lg:grid-cols-[1fr_auto]">
            <!-- Cost breakdown: usage − discounts + tax = estimated month's cost -->
            <dl class="space-y-3 rounded-lg border border-outline-gray-2 px-5 py-4 text-sm">
              <div class="flex justify-between text-ink-gray-6">
                <dt>Current usage</dt>
                <dd class="tabular-nums text-ink-gray-8">{{ money(currentUsage, currency) }}</dd>
              </div>
              <div v-if="discounts > 0" class="flex justify-between text-ink-gray-6">
                <dt>Discounts</dt>
                <dd class="tabular-nums text-ink-gray-8">− {{ money(discounts, currency) }}</dd>
              </div>
              <div v-if="taxAmount > 0" class="flex justify-between text-ink-gray-6">
                <dt>{{ taxLabel }}</dt>
                <dd class="tabular-nums text-ink-gray-8">{{ money(taxAmount, currency) }}</dd>
              </div>
              <div
                class="flex justify-between border-t border-outline-gray-1 pt-3 text-base text-ink-gray-9"
              >
                <dt>Estimated month's cost</dt>
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
        </section>

        <!-- ── Account details ────────────────────────────────────────── -->
        <section class="grid gap-4 sm:grid-cols-3">
          <!-- Billing email -->
          <div class="overflow-hidden rounded-lg border border-outline-gray-2">
            <p class="bg-surface-gray-1 px-4 py-2.5 text-sm font-medium text-ink-gray-7">Billing email</p>
            <div class="flex items-center justify-between gap-3 border-t border-outline-gray-2 px-4 py-3.5">
              <p class="truncate text-sm" :class="billingEmail ? 'text-ink-gray-8' : 'text-ink-gray-5'">
                {{ billingEmail || 'Not set' }}
              </p>
              <button
                v-if="canManage"
                class="grid size-7 shrink-0 place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
                aria-label="Edit billing email"
                @click="editProfile"
              >
                <span class="lucide-pencil size-4" />
              </button>
            </div>
          </div>

          <!-- Billing method -->
          <div class="overflow-hidden rounded-lg border border-outline-gray-2">
            <p class="bg-surface-gray-1 px-4 py-2.5 text-sm font-medium text-ink-gray-7">Billing method</p>
            <div class="flex items-center justify-between gap-3 border-t border-outline-gray-2 px-4 py-3.5">
              <p class="truncate text-sm" :class="primaryMethod ? 'text-ink-gray-8' : 'text-ink-gray-5'">
                {{ primaryMethod ? (primaryMethod.display_label || primaryMethod.method_type) : 'No payment method on file' }}
              </p>
              <Button
                v-if="canManage && primaryMethod"
                variant="ghost"
                label="Manage"
                @click="router.push({ name: 'PaymentMethods' })"
              />
              <Button
                v-else-if="canManage"
                variant="subtle"
                label="Add"
                @click="showAddMethod = true"
              >
                <template #prefix><span class="lucide-plus size-4" /></template>
              </Button>
            </div>
          </div>

          <!-- Billing address -->
          <div class="overflow-hidden rounded-lg border border-outline-gray-2">
            <p class="bg-surface-gray-1 px-4 py-2.5 text-sm font-medium text-ink-gray-7">Billing address</p>
            <div class="flex items-center justify-between gap-3 border-t border-outline-gray-2 px-4 py-3.5">
              <p class="truncate text-sm" :class="billingAddress ? 'text-ink-gray-8' : 'text-ink-gray-5'">
                {{ billingAddress || 'No address on file' }}
              </p>
              <button
                v-if="canManage"
                class="grid size-7 shrink-0 place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
                aria-label="Edit billing address"
                @click="editProfile"
              >
                <span class="lucide-pencil size-4" />
              </button>
            </div>
          </div>
        </section>

        <!-- ── Usage by project ───────────────────────────────────────── -->
        <section class="rounded-lg border border-outline-gray-1">
          <header class="flex items-center justify-between border-b border-outline-gray-1 px-4 py-3">
            <h2 class="text-base text-ink-gray-8">Usage by project</h2>
            <Button variant="ghost" label="View invoices" @click="router.push({ name: 'Invoices' })" />
          </header>
          <div v-if="!byProject.length" class="px-4 py-8 text-center text-p-sm text-ink-gray-5">
            No usage yet this cycle.
          </div>
          <ul v-else class="divide-y divide-outline-gray-1">
            <li
              v-for="p in byProject"
              :key="p.label"
              class="flex items-center justify-between gap-3 px-4 py-2.5"
            >
              <p class="truncate text-sm text-ink-gray-8">{{ p.label }}</p>
              <span class="shrink-0 text-sm tabular-nums text-ink-gray-7">{{ money(p.amount, currency) }}</span>
            </li>
          </ul>
        </section>
      </template>
    </div>

    <TopupDialog v-model="showTopup" :currency="currency" @done="onToppedUp" />
    <AddMethodDialog v-model="showAddMethod" @done="methods.reload()" />
  </div>
</template>
