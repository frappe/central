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
import { invoiceTheme } from '@/utils/status'

const { currentTeam } = useTeam()
const { canManage } = useCapabilities()

const invoices = useCall({
  url: m(API.invoices),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

// ── Filtering ──
const search = ref('')
const status = ref('all')
const tabs = [
  { label: 'All', value: 'all' },
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
          :tabs="tabs"
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
            class="flex cursor-pointer items-center justify-between gap-3 px-4 py-3 hover:bg-surface-gray-1"
            :class="selected?.name === inv.name && 'bg-surface-gray-2'"
            @click="selectRow(inv)"
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
              {{ detail.data.invoice_type }} · {{ detail.data.period_start }} →
              {{ detail.data.period_end }}
            </p>
            <p v-if="detail.data.due_date" class="text-p-sm text-ink-gray-5">
              Due {{ detail.data.due_date }}
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
