<script setup lang="ts">
import { computed, h } from 'vue'
import { Badge, Button } from 'frappe-ui'
import { ListView, type ListViewColumn, type ListViewFilter } from '@/components/common/list-view'
import { money } from '@/lib/format'
import { billingPeriod } from '@/lib/date'
import { invoiceTheme } from '@/lib/status'
import type { InvoiceSummary } from '@/types/billing'

// The team's invoices, rendered with the same ListView the server list uses.
// Presentational: it emits the clicked row; the page owns selection + the detail
// panel. Filtering/search is client-side over the curated list_invoices payload.
defineProps<{
  invoices: InvoiceSummary[]
  loading: boolean
  activeName?: string | null
}>()

const emit = defineEmits<{
  rowClick: [invoice: InvoiceSummary]
}>()

const columns = computed<ListViewColumn<InvoiceSummary>[]>(() => [
  {
    id: 'invoice',
    accessorFn: (inv) => inv.name,
    header: 'Invoice',
    size: 260,
    cell: ({ row }) =>
      h('div', { class: 'min-w-0' }, [
        h('p', { class: 'truncate text-base font-medium text-ink-gray-9' }, row.original.name),
        h(
          'p',
          { class: 'mt-0.5 truncate text-p-sm text-ink-gray-5' },
          billingPeriod(row.original.period_start, row.original.period_end),
        ),
      ]),
  },
  {
    id: 'total',
    accessorFn: (inv) => inv.total,
    header: 'Amount',
    size: 140,
    meta: { align: 'end' },
    cell: ({ row }) =>
      h(
        'span',
        { class: 'tabular-nums text-ink-gray-7' },
        money(row.original.total, row.original.currency),
      ),
  },
  {
    accessorKey: 'status',
    header: 'Status',
    size: 120,
    cell: ({ row }) =>
      h(Badge, { theme: invoiceTheme(row.original.status), label: row.original.status }),
  },
  {
    id: 'actions',
    header: '',
    size: 90,
    enableSorting: false,
    enableGlobalFilter: false,
    meta: { align: 'end' },
    // Email / download the invoice straight from the row. GROUNDING GAP (#70): no
    // backend endpoints yet, so these stay disabled until they land. The wrapper
    // stops the click from also selecting the row.
    cell: () =>
      h(
        'div',
        {
          class: 'flex items-center justify-end gap-1',
          onClick: (e: Event) => e.stopPropagation(),
        },
        [
          h(Button, {
            variant: 'ghost',
            icon: 'lucide-mail',
            disabled: true,
            title: 'Email invoice — coming soon',
            'aria-label': 'Email invoice',
          }),
          h(Button, {
            variant: 'ghost',
            icon: 'lucide-download',
            disabled: true,
            title: 'Download PDF — coming soon',
            'aria-label': 'Download invoice',
          }),
        ],
      ),
  },
])

const filters: ListViewFilter[] = [
  {
    key: 'status',
    label: 'Status',
    options: ['Open', 'Paid', 'Overdue'].map((value) => ({ label: value, value })),
  },
]
</script>

<template>
  <ListView
    :rows="invoices"
    :columns="columns"
    :row-key="(inv) => inv.name"
    :active-key="activeName"
    :loading="loading"
    :filters="filters"
    :paginated="false"
    :show-count="false"
    searchable
    search-placeholder="Search invoices…"
    item-label="invoice"
    :empty-state="{
      title: 'No invoices',
      description: 'Invoices will appear here once billing runs.',
    }"
    @row-click="emit('rowClick', $event)"
  />
</template>
