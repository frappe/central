<script setup>
import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { Badge, Button, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import ListToolbar from '@/components/ListToolbar.vue'
import SplitView from '@/components/SplitView.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayInvoice } from '@/composables/usePayInvoice'
import { money } from '@/utils/money'
import { billingPeriod, shortDate } from '@/utils/date'
import { invoiceTheme } from '@/utils/status'

const { currentTeam } = useTeam()
const { canManage } = useCapabilities()

const params = () => ({ team: currentTeam.value })
const invoices = useCall({ url: m(API.invoices), params, refetch: true })

// ── Filtering ──
const search = ref('')
const status = ref('all')
const statuses = [
  { label: 'All statuses', value: 'all' },
  { label: 'Open', value: 'open' },
  { label: 'Paid', value: 'paid' },
  { label: 'Overdue', value: 'overdue' },
]
const rows = computed(() => {
  let list = invoices.data || []
  if (status.value !== 'all') {
    list = list.filter((i) => String(i.status).toLowerCase() === status.value)
  }
  const q = search.value.trim().toLowerCase()
  if (q) list = list.filter((i) => i.name.toLowerCase().includes(q))
  return list
})

// ── Detail panel ──
const selected = ref(null)
const detailOpen = computed({
  get: () => !!selected.value,
  set: (v) => { if (!v) selected.value = null },
})
const detail = useCall({ url: m(API.invoice), immediate: false })

async function selectRow(inv) {
  selected.value = inv
  await detail.submit({ name: inv.name })
}

const canPay = computed(
  () => canManage.value && String(detail.data?.status).toLowerCase() === 'open',
)

const { run: payInvoice, loading: paying } = usePayInvoice({
  onDone: () => {
    invoices.reload?.()
    if (selected.value) detail.submit({ name: selected.value.name })
  },
})

// Timeline dot colour per event theme.
const DOTS = {
  green: 'bg-surface-green-5',
  red: 'bg-surface-red-5',
  blue: 'bg-surface-blue-5',
  orange: 'bg-surface-amber-5',
  gray: 'bg-surface-gray-4',
}
const dotClass = (theme) => DOTS[theme] || DOTS.gray
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Billing' }, { label: 'Invoices' }]" />

    <SplitView v-model:open="detailOpen" class="flex-1">
      <!-- LIST -->
      <template #list>
        <ListToolbar
          v-model:search="search"
          v-model:status="status"
          :statuses="statuses"
          placeholder="Search invoices…"
        />
        <div v-if="invoices.loading && !invoices.data" class="space-y-3 p-4">
          <LoadingText :lines="6" />
        </div>
        <div v-else-if="!rows.length" class="px-4 py-12 text-center text-p-sm text-ink-gray-5">
          No invoices match.
        </div>
        <ul v-else class="divide-y divide-outline-gray-1">
          <li
            v-for="inv in rows"
            :key="inv.name"
            class="flex cursor-pointer items-center gap-3 px-4 py-2.5 hover:bg-surface-gray-1"
            :class="selected?.name === inv.name && 'bg-surface-gray-2'"
            @click="selectRow(inv)"
          >
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-ink-gray-8">{{ inv.name }}</p>
              <p class="truncate text-p-sm text-ink-gray-5">
                {{ billingPeriod(inv.period_start, inv.period_end) }}
              </p>
            </div>
            <span class="shrink-0 text-sm tabular-nums text-ink-gray-7">
              {{ money(inv.total, inv.currency) }}
            </span>
            <Badge :theme="invoiceTheme(inv.status)" :label="inv.status" class="shrink-0" />
          </li>
        </ul>
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

          <!-- Line items -->
          <div class="rounded border border-outline-gray-1">
            <table class="w-full text-sm">
              <thead>
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
            <div class="flex justify-between border-t border-outline-gray-1 pt-1.5 text-base text-ink-gray-9">
              <dt>Total</dt>
              <dd>{{ money(detail.data.total, detail.data.currency) }}</dd>
            </div>
            <div v-if="detail.data.amount_paid" class="flex justify-between text-ink-gray-6">
              <dt>Paid</dt>
              <dd>{{ money(detail.data.amount_paid, detail.data.currency) }}</dd>
            </div>
          </dl>

          <!-- Activity: the invoice's full lifecycle as a timeline (finalised →
               credits applied → card attempts incl. failures → settled). -->
          <section
            v-if="detail.data.activity?.length"
            class="border-t border-outline-gray-2 pt-5"
          >
            <p class="mb-3 text-p-sm font-medium uppercase tracking-wide text-ink-gray-5">
              Activity
            </p>
            <ol class="space-y-0">
              <li
                v-for="(ev, idx) in detail.data.activity"
                :key="idx"
                class="relative flex gap-3 pb-4 last:pb-0"
              >
                <!-- connector line -->
                <span
                  v-if="idx < detail.data.activity.length - 1"
                  class="absolute left-[5px] top-3 h-full w-px bg-outline-gray-2"
                />
                <span class="relative mt-1 size-2.5 shrink-0 rounded-full" :class="dotClass(ev.theme)" />
                <div class="min-w-0 flex-1">
                  <div class="flex items-start justify-between gap-2">
                    <p class="text-sm text-ink-gray-8">{{ ev.title }}</p>
                    <span v-if="ev.amount" class="shrink-0 text-sm text-ink-gray-7">
                      {{ money(ev.amount, ev.currency || detail.data.currency) }}
                    </span>
                  </div>
                  <p v-if="ev.detail" class="break-words text-p-sm text-ink-gray-5">{{ ev.detail }}</p>
                  <p class="text-p-sm text-ink-gray-4">{{ ev.at }}</p>
                </div>
              </li>
            </ol>
          </section>

          <Button
            v-if="canPay"
            variant="solid"
            :label="`Pay ${money(detail.data.expected_collection, detail.data.currency)}`"
            :loading="paying"
            class="w-full"
            @click="payInvoice(detail.data.name)"
          />
        </div>
      </template>
    </SplitView>
  </div>
</template>
