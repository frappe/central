<script setup lang="ts">
import { computed, h } from 'vue'
import { Button } from 'frappe-ui'
import {
  ListView,
  type ListViewColumn,
  type ListViewFilter,
  type ListViewQuery,
} from '@/components/common/list-view'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import ServerStatusBadge from '@/components/servers/ServerStatusBadge.vue'
import { formatSpecs } from '@/lib/format'
import type { Server } from '@/types'

const props = defineProps<{
  servers: Server[]
  totalRows: number
  countLoading: boolean
  query: ListViewQuery
  loading: boolean
  error: string | null
  canCreate: boolean
  canPower: boolean
  canTerminate: boolean
  canOpen: boolean
  busy: string
  opening: string
}>()

const emit = defineEmits<{
  'update:query': [query: ListViewQuery]
  retry: []
  create: []
  start: [server: Server]
  stop: [server: Server]
  terminate: [server: Server]
  open: [server: Server]
}>()

const columns = computed<ListViewColumn<Server>[]>(() => [
  {
    id: 'title',
    accessorFn: (server) => server.title || server.resource_id,
    header: 'Name',
    size: 280,
    cell: ({ row }) =>
      h('div', { class: 'min-w-0' }, [
        h(
          'p',
          { class: 'truncate font-medium text-ink-gray-9' },
          row.original.title || row.original.resource_id,
        ),
        h(
          'p',
          { class: 'mt-0.5 truncate text-p-sm text-ink-gray-5 sm:hidden' },
          formatSpecs(row.original),
        ),
      ]),
  },
  {
    accessorKey: 'cluster',
    header: 'Region',
    size: 180,
    cell: ({ getValue }) => h('span', { class: 'text-ink-gray-7' }, String(getValue())),
  },
  {
    id: 'specs',
    accessorFn: formatSpecs,
    header: 'Specs',
    size: 220,
    enableSorting: false,
    cell: ({ getValue }) => h('span', { class: 'text-ink-gray-7' }, String(getValue())),
    meta: {
      headerClass: 'hidden sm:table-cell',
      cellClass: 'hidden sm:table-cell',
    },
  },
  {
    accessorKey: 'status',
    header: 'Status',
    size: 140,
    cell: ({ row }) => h(ServerStatusBadge, { status: row.original.status }),
  },
  {
    id: 'actions',
    header: 'Actions',
    size: 120,
    enableSorting: false,
    enableGlobalFilter: false,
    meta: { align: 'end' },
    cell: ({ row }) =>
      h('div', { class: 'flex items-center justify-end' }, [
        h(ServerRowActions, {
          server: row.original,
          canOpen: props.canOpen,
          canPower: props.canPower,
          canTerminate: props.canTerminate,
          busy: props.busy === row.original.resource_id,
          opening: props.opening === row.original.resource_id,
          onOpen: (server: Server) => emit('open', server),
          onStart: (server: Server) => emit('start', server),
          onStop: (server: Server) => emit('stop', server),
          onTerminate: (server: Server) => emit('terminate', server),
        }),
      ]),
  },
])

const filters: ListViewFilter[] = [
  {
    key: 'status',
    label: 'Status',
    options: ['Pending', 'Provisioning', 'Running', 'Paused', 'Stopped', 'Failed', 'Terminated']
      .map((value) => ({ label: value, value })),
  },
]
</script>

<template>
  <ListView
    :rows="servers"
    :query="query"
    :columns="columns"
    :row-key="(server) => server.resource_id"
    :loading="loading"
    :error="error"
    :filters="filters"
    :total-rows="totalRows"
    :count-loading="countLoading"
    item-label="server"
    server-side
    searchable
    search-placeholder="Search servers…"
    :empty-state="{
      title: 'No servers yet',
      description: 'Spin one up to see it here, kept in sync with Atlas.',
    }"
    @update:query="$emit('update:query', $event)"
    @retry="$emit('retry')"
  >
    <template v-if="canCreate" #empty-action>
      <Button variant="solid" label="New server" icon-left="lucide-plus" @click="$emit('create')" />
    </template>
  </ListView>
</template>
