<script setup lang="ts">
import { computed, h } from 'vue'
import { Badge } from 'frappe-ui'
import { ListView, type ListViewColumn } from '@/components/common/list-view'
import PaymentMethodRowActions from '@/components/billing/PaymentMethodRowActions.vue'
import type { PaymentMethod } from '@/types/billing'

// The team's payment methods, rendered with the same ListView the rest of billing
// uses. Presentational: it emits the chosen verb; the card owns the calls. The
// rows arrive in fallback order, so the row index is the fallback rank — sorting
// is disabled to keep that order meaningful.
const props = defineProps<{
  methods: PaymentMethod[]
  loading: boolean
  canManage: boolean
  busy: string
}>()

const emit = defineEmits<{
  makeDefault: [pm: PaymentMethod]
  moveUp: [pm: PaymentMethod]
  moveDown: [pm: PaymentMethod]
  remove: [pm: PaymentMethod]
}>()

function methodIcon(type: string): string {
  return type === 'Card' ? 'lucide-credit-card' : 'lucide-smartphone'
}

function details(pm: PaymentMethod, rank: number): string {
  const parts = [pm.method_type]
  if (pm.expiry_month && pm.expiry_year)
    parts.push(`expires ${String(pm.expiry_month).padStart(2, '0')}/${pm.expiry_year}`)
  parts.push(`fallback #${rank}`)
  return parts.join(' · ')
}

const columns = computed<ListViewColumn<PaymentMethod>[]>(() => [
  {
    id: 'method',
    accessorFn: (pm) => pm.display_label || pm.method_type,
    header: 'Method',
    size: 320,
    enableSorting: false,
    cell: ({ row }) =>
      h('div', { class: 'flex min-w-0 items-center gap-3' }, [
        h('span', {
          class: [methodIcon(row.original.method_type), 'size-5 shrink-0 text-ink-gray-5'],
          'aria-hidden': 'true',
        }),
        h('div', { class: 'min-w-0' }, [
          h(
            'p',
            { class: 'truncate text-base font-medium text-ink-gray-9' },
            row.original.display_label || row.original.method_type,
          ),
          h(
            'p',
            { class: 'mt-0.5 truncate text-p-sm text-ink-gray-5' },
            details(row.original, row.index + 1),
          ),
        ]),
      ]),
  },
  {
    id: 'status',
    header: 'Status',
    size: 200,
    enableSorting: false,
    cell: ({ row }) =>
      h('div', { class: 'flex flex-wrap items-center gap-2' }, [
        row.original.is_default ? h(Badge, { theme: 'green', label: 'Default' }) : null,
        row.original.reauth_required
          ? h(Badge, { theme: 'orange', label: 'Re-auth needed' })
          : null,
        row.original.status !== 'Active'
          ? h(Badge, { theme: 'gray', label: row.original.status })
          : null,
      ]),
  },
  {
    id: 'actions',
    header: 'Actions',
    size: 80,
    enableSorting: false,
    meta: { align: 'end' },
    cell: ({ row }) =>
      h('div', { class: 'flex items-center justify-end' }, [
        h(PaymentMethodRowActions, {
          method: row.original,
          canManage: props.canManage,
          isFirst: row.index === 0,
          isLast: row.index === props.methods.length - 1,
          busy: props.busy === row.original.name,
          onMakeDefault: (pm: PaymentMethod) => emit('makeDefault', pm),
          onMoveUp: (pm: PaymentMethod) => emit('moveUp', pm),
          onMoveDown: (pm: PaymentMethod) => emit('moveDown', pm),
          onRemove: (pm: PaymentMethod) => emit('remove', pm),
        }),
      ]),
  },
])
</script>

<template>
  <ListView
    :rows="methods"
    :columns="columns"
    :row-key="(pm) => pm.name"
    :loading="loading"
    :paginated="false"
    :show-count="false"
    item-label="payment method"
    :empty-state="{
      title: 'No payment methods yet',
      description: 'Add a card or UPI Autopay so invoices can be charged automatically.',
    }"
  />
</template>
