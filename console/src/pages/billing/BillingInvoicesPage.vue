<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCall, Badge, Button, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import InvoiceListView from '@/components/billing/InvoiceListView.vue'
import SplitView from '@/components/common/SplitView.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayInvoice } from '@/composables/usePayInvoice'
import { usePayInvoiceCheckout } from '@/composables/usePayInvoiceCheckout'
import { money } from '@/lib/format'
import { billingPeriod, shortDate } from '@/lib/date'
import { invoiceTheme } from '@/lib/status'
import type { InvoiceSummary, InvoiceDetail, CollectionStatus } from '@/types/billing'

// Billing › Invoices (#70) — split list (left) + ~480px detail panel (right), not
// a modal. Invoices come from the team-scoped list_invoices/get_invoice endpoints
// (curated fields, not raw reportview), so we filter client-side over that list.
const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const params = () => ({ team: activeTeam.value! })
const invoices = useCall<InvoiceSummary[], { team: string }>({
  url: method(API.invoices), params, immediate: false, refetch: true,
})
const collection = useCall<CollectionStatus, { team: string }>({
  url: method(API.collectionStatus), params, immediate: false, refetch: true,
})
whenTeamReady(() => {
  invoices.reload()
  collection.reload()
})

// ── Detail panel ──
const selected = ref<InvoiceSummary | null>(null)
const detailOpen = computed({
  get: () => !!selected.value,
  set: (v) => {
    if (!v) selected.value = null
  },
})
const detail = useCall<InvoiceDetail, { name: string }>({
  url: method(API.invoice), immediate: false,
})

async function selectRow(inv: InvoiceSummary): Promise<void> {
  selected.value = inv
  await detail.submit({ name: inv.name })
}

const canPay = computed(
  () => canManageBilling.value && String(detail.data?.status).toLowerCase() === 'open',
)

function refresh(): void {
  invoices.reload()
  if (selected.value) detail.submit({ name: selected.value.name })
}
const { run: payInvoice, loading: paying } = usePayInvoice({ onDone: refresh })
const { run: payCheckout, loading: payingCheckout } = usePayInvoiceCheckout({ onDone: refresh })

// manual_checkout teams settle on-session (any amount, no ₹15k limit); everyone
// else uses the off-session charge against their saved method.
const manualMode = computed(() => collection.data?.collection_mode === 'Manual Checkout')
const payBusy = computed(() => paying.value || payingCheckout.value)
function pay(name: string): Promise<unknown> {
  return manualMode.value ? payCheckout(name) : payInvoice(name)
}

// Timeline dot colour per event theme.
const DOTS: Record<string, string> = {
  green: 'bg-surface-green-5',
  red: 'bg-surface-red-5',
  blue: 'bg-surface-blue-5',
  orange: 'bg-surface-amber-5',
  gray: 'bg-surface-gray-4',
}
const dotClass = (theme: string): string => DOTS[theme] || DOTS.gray
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Invoices" subtitle="Billing" />

    <SplitView v-model:open="detailOpen" class="flex-1">
      <!-- Document actions, pinned to the detail header. GROUNDING GAP (#70): no
           email-invoice / download-PDF endpoints yet, so these stay disabled
           until the backend lands them. -->
      <template v-if="detail.data" #actions>
        <Button
          variant="ghost"
          icon="lucide-mail"
          :disabled="true"
          title="Email invoice — coming soon"
        />
        <Button
          variant="ghost"
          icon="lucide-download"
          :disabled="true"
          title="Download PDF — coming soon"
        />
      </template>

      <!-- LIST -->
      <template #list>
        <div class="px-4 py-5 sm:px-6">
          <InvoiceListView
            :invoices="invoices.data ?? []"
            :loading="invoices.loading && !invoices.data"
            :active-name="selected?.name"
            @row-click="selectRow"
          />
        </div>
      </template>

      <!-- DETAIL -->
      <template #detail>
        <div v-if="detail.loading && !detail.data" class="space-y-3 p-4">
          <LoadingText :lines="6" />
        </div>
        <div v-else-if="detail.data" class="flex flex-col gap-5 p-4">
          <header class="space-y-2">
            <div class="flex items-center justify-between gap-2">
              <h2 class="text-base text-ink-gray-9">{{ detail.data.name }}</h2>
              <Badge :theme="invoiceTheme(detail.data.status)" :label="detail.data.status" />
            </div>
            <p class="text-p-sm text-ink-gray-5">
              {{ detail.data.invoice_type }} ·
              {{ billingPeriod(detail.data.period_start, detail.data.period_end) }}
            </p>
            <p v-if="detail.data.due_date" class="text-p-sm text-ink-gray-5">
              Due {{ shortDate(detail.data.due_date) }}
            </p>
          </header>

          <!-- Line items. A long fleet can run to dozens of rows, so the list gets
               its own bounded scroll (sticky header). -->
          <div>
            <div class="mb-1.5 flex items-center justify-between">
              <p class="text-p-sm font-medium uppercase tracking-wide text-ink-gray-5">
                Line items
              </p>
              <span class="text-p-sm text-ink-gray-5">
                {{ detail.data.items.length }} item{{ detail.data.items.length === 1 ? '' : 's' }}
              </span>
            </div>
            <div class="max-h-80 overflow-y-auto rounded border border-outline-gray-1">
              <table class="w-full text-sm">
                <thead class="sticky top-0 bg-surface-elevation-1">
                  <tr class="border-b border-outline-gray-1 text-left text-p-sm text-ink-gray-5">
                    <th class="px-3 py-2 font-normal">Item</th>
                    <th class="px-3 py-2 text-right font-normal">Amount</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-outline-gray-1">
                  <tr v-for="(li, idx) in detail.data.items" :key="idx">
                    <td class="px-3 py-2">
                      <p class="text-ink-gray-8">{{ li.item }}</p>
                      <p v-if="li.detail" class="text-p-sm text-ink-gray-5">{{ li.detail }}</p>
                    </td>
                    <td class="px-3 py-2 text-right text-ink-gray-8">
                      {{ money(li.amount, detail.data.currency) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Totals -->
          <dl class="space-y-1.5 text-sm">
            <div class="flex justify-between text-ink-gray-6">
              <dt>Subtotal</dt>
              <dd>{{ money(detail.data.subtotal, detail.data.currency) }}</dd>
            </div>
            <div v-if="detail.data.output_tax_amount" class="flex justify-between text-ink-gray-6">
              <dt>{{ detail.data.output_tax_type || 'Tax' }}</dt>
              <dd>{{ money(detail.data.output_tax_amount, detail.data.currency) }}</dd>
            </div>
            <p v-if="detail.data.zero_rating_reason" class="text-p-sm text-ink-gray-5">
              {{ detail.data.zero_rating_reason }}
            </p>
            <div v-if="detail.data.credit_applied" class="flex justify-between text-ink-green-3">
              <dt>Credit applied</dt>
              <dd>− {{ money(detail.data.credit_applied, detail.data.currency) }}</dd>
            </div>
            <div
              class="flex justify-between border-t border-outline-gray-1 pt-1.5 text-base text-ink-gray-9"
            >
              <dt>Total</dt>
              <dd>{{ money(detail.data.total, detail.data.currency) }}</dd>
            </div>
            <div v-if="detail.data.amount_paid" class="flex justify-between text-ink-gray-6">
              <dt>Paid</dt>
              <dd>{{ money(detail.data.amount_paid, detail.data.currency) }}</dd>
            </div>
          </dl>

          <!-- Activity: the invoice's full lifecycle as a timeline. -->
          <section v-if="detail.data.activity?.length" class="border-t border-outline-gray-2 pt-5">
            <p class="mb-3 text-p-sm font-medium uppercase tracking-wide text-ink-gray-5">
              Activity
            </p>
            <ol class="space-y-0">
              <li
                v-for="(ev, idx) in detail.data.activity"
                :key="idx"
                class="relative flex gap-3 pb-4 last:pb-0"
              >
                <span
                  v-if="idx < detail.data.activity.length - 1"
                  class="absolute left-[5px] top-3 h-full w-px bg-outline-gray-2"
                />
                <span
                  class="relative mt-1 size-2.5 shrink-0 rounded-full"
                  :class="dotClass(ev.theme)"
                />
                <div class="min-w-0 flex-1">
                  <div class="flex items-start justify-between gap-2">
                    <p class="text-sm text-ink-gray-8">{{ ev.title }}</p>
                    <span v-if="ev.amount" class="shrink-0 text-sm text-ink-gray-7">
                      {{ money(ev.amount, ev.currency || detail.data.currency) }}
                    </span>
                  </div>
                  <p v-if="ev.detail" class="break-words text-p-sm text-ink-gray-5">
                    {{ ev.detail }}
                  </p>
                  <p class="text-p-sm text-ink-gray-4">{{ ev.at }}</p>
                </div>
              </li>
            </ol>
          </section>

          <!-- Pinned so the pay action is always reachable. -->
          <div
            v-if="canPay"
            class="sticky bottom-0 -mx-4 -mb-4 border-t border-outline-gray-1 bg-surface-elevation-1 px-4 py-3"
          >
            <Button
              variant="solid"
              :label="`Pay ${money(detail.data.expected_collection, detail.data.currency)}`"
              :loading="payBusy"
              class="w-full"
              @click="pay(detail.data.name)"
            />
          </div>
        </div>
      </template>
    </SplitView>
  </div>
</template>
