<script setup lang="ts">
import { computed, h } from 'vue'
import { Badge } from 'frappe-ui'
import { ListView, type ListViewColumn } from '@/components/common/list-view'
import SubscriptionRowActions from '@/components/billing/SubscriptionRowActions.vue'
import { money } from '@/lib/format'
import type { SubscriptionRow } from '@/types/billing'

// The team's subscriptions, rendered with the same ListView the server list uses.
// Presentational: it emits the chosen verb; the parent card owns the calls.
const props = defineProps<{
  subscriptions: SubscriptionRow[]
  loading: boolean
  canManage: boolean
  busy: string
}>()

const emit = defineEmits<{
  open: [sub: SubscriptionRow]
  pause: [sub: SubscriptionRow]
  resume: [sub: SubscriptionRow]
}>()

// Title falls back server → plan → id; subtitle is "plan · region", skipping the
// plan when it is already serving as the title (a server with no friendly name).
function title(sub: SubscriptionRow): string {
  return sub.server || sub.plan_title || sub.name
}
function subtitle(sub: SubscriptionRow): string {
  const parts: string[] = []
  if (sub.plan_title && sub.plan_title !== title(sub)) parts.push(sub.plan_title)
  if (sub.region) parts.push(sub.region)
  return parts.join(' · ') || sub.billing_cycle || 'Monthly'
}

const columns = computed<ListViewColumn<SubscriptionRow>[]>(() => [
  {
    id: 'title',
    accessorFn: (sub) => title(sub),
    header: 'Server',
    size: 280,
    cell: ({ row }) =>
      h('div', { class: 'min-w-0' }, [
        h('p', { class: 'truncate text-base font-medium text-ink-gray-9' }, title(row.original)),
        h('p', { class: 'mt-0.5 truncate text-p-sm text-ink-gray-5' }, subtitle(row.original)),
      ]),
  },
  {
    id: 'price',
    accessorFn: (sub) => sub.monthly_rate ?? 0,
    header: 'Price',
    size: 140,
    cell: ({ row }) =>
      h(
        'span',
        { class: 'text-ink-gray-7' },
        row.original.monthly_rate != null
          ? `${money(row.original.monthly_rate, row.original.currency, { trimTrailingZeros: true })}/mo`
          : '—',
      ),
  },
  {
    id: 'status',
    accessorFn: (sub) => (sub.enabled ? 'Running' : 'Paused'),
    header: 'Status',
    size: 140,
    cell: ({ row }) =>
      h(Badge, {
        theme: row.original.enabled ? 'green' : 'gray',
        label: row.original.enabled ? 'Running' : 'Paused',
      }),
  },
  {
    id: 'actions',
    header: 'Actions',
    size: 100,
    enableSorting: false,
    enableGlobalFilter: false,
    meta: { align: 'end' },
    cell: ({ row }) =>
      h('div', { class: 'flex items-center justify-end' }, [
        h(SubscriptionRowActions, {
          subscription: row.original,
          canManage: props.canManage,
          busy: props.busy === row.original.name,
          onOpen: (sub: SubscriptionRow) => emit('open', sub),
          onPause: (sub: SubscriptionRow) => emit('pause', sub),
          onResume: (sub: SubscriptionRow) => emit('resume', sub),
        }),
      ]),
  },
])
</script>

<template>
  <ListView
    :rows="subscriptions"
    :columns="columns"
    :row-key="(sub) => sub.name"
    :loading="loading"
    :paginated="false"
    :show-count="false"
    item-label="subscription"
    :empty-state="{
      title: 'No active subscriptions',
      description: 'Your active server plans will appear here.',
    }"
  />
</template>
