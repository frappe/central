<script setup lang="ts" generic="TData extends object">
import { computed, h, ref } from 'vue'
import { Button, Checkbox, Combobox, TextInput } from 'frappe-ui'
import {
  FlexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useVueTable,
  type ColumnDef,
  type ColumnFiltersState,
  type PaginationState,
  type Row,
  type RowSelectionState,
  type SortingState,
  type Updater,
} from '@tanstack/vue-table'
import ListViewPagination from './ListViewPagination.vue'
import ListViewState from './ListViewState.vue'
import {
  createListViewQuery,
  type ListViewEmptyState,
  type ListViewFilter,
  type ListViewQuery,
} from './types'

const props = withDefaults(
  defineProps<{
    rows: TData[]
    columns: ColumnDef<TData, unknown>[]
    rowKey: (row: TData) => string
    loading?: boolean
    error?: string | null
    searchable?: boolean
    searchPlaceholder?: string
    filters?: ListViewFilter[]
    selectable?: boolean
    paginated?: boolean
    serverSide?: boolean
    totalRows?: number
    countLoading?: boolean
    itemLabel?: string
    showCount?: boolean
    emptyState?: ListViewEmptyState
  }>(),
  {
    loading: false,
    error: null,
    searchable: false,
    searchPlaceholder: 'Search…',
    filters: () => [],
    selectable: false,
    paginated: true,
    serverSide: false,
    totalRows: 0,
    countLoading: false,
    itemLabel: 'row',
    showCount: true,
    emptyState: () => ({
      title: 'No data',
      description: 'There is nothing to show yet.',
    }),
  },
)

const query = defineModel<ListViewQuery>('query', {
  default: () => createListViewQuery(),
})

const emit = defineEmits<{
  retry: []
  rowClick: [row: TData]
  selectionChange: [rows: TData[]]
}>()

const rowSelection = ref<RowSelectionState>({})

const selectionColumn = computed<ColumnDef<TData, unknown>>(() => ({
  id: '__selection',
  size: 44,
  minSize: 44,
  maxSize: 44,
  enableSorting: false,
  enableHiding: false,
  header: ({ table }) =>
    h(Checkbox, {
      modelValue: table.getIsAllPageRowsSelected(),
      'aria-label': 'Select all rows on this page',
      'onUpdate:modelValue': (...args: unknown[]) =>
        table.toggleAllPageRowsSelected(Boolean(args[0])),
    }),
  cell: ({ row }) =>
    h(Checkbox, {
      modelValue: row.getIsSelected(),
      disabled: !row.getCanSelect(),
      'aria-label': `Select row ${row.id}`,
      onClick: (event: Event) => event.stopPropagation(),
      'onUpdate:modelValue': (...args: unknown[]) => row.toggleSelected(Boolean(args[0])),
    }),
  meta: {
    cellClass: 'px-3',
    headerClass: 'px-3',
  },
}))

const tableColumns = computed(() =>
  props.selectable ? [selectionColumn.value, ...props.columns] : props.columns,
)

const table = useVueTable({
  get data() {
    return props.rows
  },
  get columns() {
    return tableColumns.value
  },
  getRowId: (row) => props.rowKey(row),
  enableRowSelection: props.selectable,
  manualFiltering: props.serverSide,
  manualPagination: props.serverSide,
  manualSorting: props.serverSide,
  get rowCount() {
    return props.serverSide ? props.totalRows : undefined
  },
  getCoreRowModel: getCoreRowModel(),
  getFilteredRowModel: getFilteredRowModel(),
  getSortedRowModel: getSortedRowModel(),
  getPaginationRowModel:
    props.paginated && !props.serverSide ? getPaginationRowModel() : undefined,
  state: {
    get sorting() {
      return query.value.sort
        ? [{ id: query.value.sort.key, desc: query.value.sort.direction === 'desc' }]
        : []
    },
    get globalFilter() {
      return query.value.search
    },
    get columnFilters() {
      return Object.entries(query.value.filters)
        .filter(([, value]) => value !== '')
        .map(([id, value]) => ({ id, value }))
    },
    get pagination() {
      return {
        pageIndex: query.value.page - 1,
        pageSize: query.value.pageSize,
      }
    },
    get rowSelection() {
      return rowSelection.value
    },
  },
  onSortingChange: updateSorting,
  onGlobalFilterChange: updateSearch,
  onColumnFiltersChange: updateColumnFilters,
  onPaginationChange: updatePagination,
  onRowSelectionChange: (updater) => {
    updateRef(updater, rowSelection)
    emit(
      'selectionChange',
      table.getSelectedRowModel().rows.map((row) => row.original),
    )
  },
})

const visibleColumnCount = computed(() => table.getVisibleLeafColumns().length)
const filteredRows = computed(() => table.getFilteredRowModel().rows)
const pageRows = computed(() => table.getRowModel().rows)
const hasRows = computed(() => props.rows.length > 0)
const hasActiveQuery = computed(
  () => query.value.search !== '' || Object.values(query.value.filters).some(Boolean),
)
const resultCount = computed(() =>
  props.serverSide ? props.totalRows : filteredRows.value.length,
)
const countText = computed(() => {
  const label = resultCount.value === 1 ? props.itemLabel : `${props.itemLabel}s`
  return `${resultCount.value.toLocaleString()} ${label}`
})
const showPagination = computed(
  () => props.paginated && resultCount.value > 0 && !props.loading,
)
const pagination = computed(() => table.getState().pagination)

function clearFilters(): void {
  query.value = {
    ...query.value,
    page: 1,
    search: '',
    filters: {},
  }
}

function updateFilter(key: string, value: unknown): void {
  query.value = {
    ...query.value,
    page: 1,
    filters: {
      ...query.value.filters,
      [key]: typeof value === 'string' ? value : '',
    },
  }
}

function updateSearch(updater: Updater<unknown>): void {
  const next = applyUpdater(updater, query.value.search)
  query.value = { ...query.value, page: 1, search: String(next ?? '') }
}

function updateSorting(updater: Updater<SortingState>): void {
  const current: SortingState = query.value.sort
    ? [{ id: query.value.sort.key, desc: query.value.sort.direction === 'desc' }]
    : []
  const next = applyUpdater(updater, current)[0]
  query.value = {
    ...query.value,
    page: 1,
    sort: next
      ? { key: next.id, direction: next.desc ? 'desc' : 'asc' }
      : null,
  }
}

function updateColumnFilters(updater: Updater<ColumnFiltersState>): void {
  const current = Object.entries(query.value.filters).map(([id, value]) => ({ id, value }))
  const next = applyUpdater(updater, current)
  query.value = {
    ...query.value,
    page: 1,
    filters: Object.fromEntries(next.map(({ id, value }) => [id, String(value ?? '')])),
  }
}

function updatePagination(updater: Updater<PaginationState>): void {
  const next = applyUpdater(updater, pagination.value)
  query.value = {
    ...query.value,
    page: next.pageIndex + 1,
    pageSize: next.pageSize,
  }
}

function sortAria(column: ReturnType<typeof table.getAllLeafColumns>[number]) {
  const sorted = column.getIsSorted()
  return sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'
}

function alignClass(align?: 'start' | 'center' | 'end'): string {
  if (align === 'center') return 'text-center'
  if (align === 'end') return 'text-right'
  return 'text-left'
}

function handleRowClick(row: Row<TData>): void {
  emit('rowClick', row.original)
}

function updateRef<T>(updater: Updater<T>, target: { value: T }): void {
  target.value = applyUpdater(updater, target.value)
}

function applyUpdater<T>(updater: Updater<T>, previous: T): T {
  return typeof updater === 'function'
    ? (updater as (value: T) => T)(previous)
    : updater
}

defineExpose({ table })
</script>

<template>
  <section class="min-w-0">
    <div
      v-if="searchable || filters.length || showCount || $slots.toolbar"
      class="flex flex-wrap items-center justify-between gap-3 pb-3"
    >
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        <TextInput
          v-if="searchable"
          :model-value="query.search"
          class="w-full sm:w-64"
          :placeholder="searchPlaceholder"
          :debounce="250"
          @update:model-value="table.setGlobalFilter(String($event))"
        >
          <template #prefix>
            <span class="lucide-search size-4" aria-hidden="true" />
          </template>
        </TextInput>
        <Combobox
          v-for="filter in filters"
          :key="filter.key"
          :model-value="query.filters[filter.key] || ''"
          class="w-40"
          trigger="button"
          variant="outline"
          :placeholder="filter.allLabel || `All ${filter.label.toLowerCase()}`"
          :options="[
            {
              label: filter.allLabel || `All ${filter.label.toLowerCase()}`,
              value: '',
            },
            ...filter.options,
          ]"
          @update:model-value="updateFilter(filter.key, $event)"
        />
        <Button
          v-if="hasActiveQuery"
          label="Clear filters"
          variant="ghost"
          @click="clearFilters"
        />
      </div>
      <div class="ml-auto flex shrink-0 items-center gap-3">
        <slot name="toolbar" :table="table" />
        <div v-if="showCount" class="flex min-w-16 justify-end">
          <div
            v-if="countLoading"
            class="h-3 w-12 animate-pulse rounded bg-surface-gray-2"
            aria-label="Loading result count"
          />
          <p v-else class="whitespace-nowrap text-p-sm text-ink-gray-5">
            {{ countText }}
          </p>
        </div>
      </div>
    </div>

    <div
      v-if="selectable && table.getSelectedRowModel().rows.length"
      class="mb-2 flex flex-wrap items-center justify-between gap-3 rounded bg-surface-blue-1 px-3 py-2"
    >
      <p class="text-p-sm font-medium text-ink-blue-8">
        {{ table.getSelectedRowModel().rows.length }} selected
      </p>
      <div class="flex items-center gap-2">
        <slot
          name="selection-actions"
          :rows="table.getSelectedRowModel().rows.map((row) => row.original)"
          :clear="table.resetRowSelection"
        />
        <Button label="Clear" variant="ghost" @click="table.resetRowSelection()" />
      </div>
    </div>

    <div
      v-if="error && hasRows"
      class="mb-2 flex items-center justify-between gap-3 rounded bg-surface-red-1 px-3 py-2"
      role="alert"
    >
      <p class="text-p-sm text-ink-red-7">{{ error }}</p>
      <Button label="Retry" variant="ghost" @click="$emit('retry')" />
    </div>

    <div class="relative overflow-x-auto">
      <div
        v-if="loading && hasRows"
        class="absolute inset-x-0 top-0 z-10 h-0.5 animate-pulse bg-surface-blue-5"
        aria-label="Refreshing list"
      />

      <table class="w-full min-w-[720px] border-collapse text-left">
        <thead v-if="hasRows || loading">
          <tr class="border-y border-outline-gray-2 bg-surface-gray-1">
            <th
              v-for="header in table.getFlatHeaders()"
              :key="header.id"
              scope="col"
              :aria-sort="header.column.getCanSort() ? sortAria(header.column) : undefined"
              class="h-10 px-4 text-p-sm font-medium text-ink-gray-5"
              :class="[
                alignClass(header.column.columnDef.meta?.align),
                header.column.columnDef.meta?.headerClass,
              ]"
              :style="{ width: `${header.getSize()}px` }"
            >
              <button
                v-if="!header.isPlaceholder && header.column.getCanSort()"
                type="button"
                class="inline-flex items-center gap-1.5 rounded-sm outline-none hover:text-ink-gray-8 focus-visible:ring-2 focus-visible:ring-outline-blue-2"
                @click="header.column.getToggleSortingHandler()?.($event)"
              >
                <FlexRender
                  :render="header.column.columnDef.header"
                  :props="header.getContext()"
                />
                <span
                  :class="[
                    header.column.getIsSorted() === 'asc'
                      ? 'lucide-arrow-up'
                      : header.column.getIsSorted() === 'desc'
                        ? 'lucide-arrow-down'
                        : 'lucide-arrow-up-down opacity-60',
                    'size-3.5',
                  ]"
                  aria-hidden="true"
                />
              </button>
              <FlexRender
                v-else-if="!header.isPlaceholder"
                :render="header.column.columnDef.header"
                :props="header.getContext()"
              />
            </th>
          </tr>
        </thead>

        <tbody v-if="loading && !hasRows" class="divide-y divide-outline-gray-1">
          <tr v-for="rowIndex in 5" :key="rowIndex">
            <td v-for="column in visibleColumnCount" :key="column" class="h-14 px-4">
              <div
                class="h-3 animate-pulse rounded bg-surface-gray-2"
                :class="column === 1 ? 'w-2/3' : 'w-1/2'"
              />
            </td>
          </tr>
        </tbody>

        <tbody v-else-if="error && !hasRows">
          <tr>
            <td :colspan="visibleColumnCount">
              <ListViewState
                kind="error"
                title="Couldn't load this list"
                :description="error"
                @retry="$emit('retry')"
              />
            </td>
          </tr>
        </tbody>

        <tbody v-else-if="!hasRows && hasActiveQuery">
          <tr>
            <td :colspan="visibleColumnCount">
              <ListViewState
                kind="filtered"
                title="No matching results"
                description="Change or clear the filters to see more results."
                @clear="clearFilters"
              />
            </td>
          </tr>
        </tbody>

        <tbody v-else-if="!hasRows">
          <tr>
            <td :colspan="visibleColumnCount">
              <ListViewState
                kind="empty"
                :title="emptyState.title"
                :description="emptyState.description"
              >
                <template v-if="$slots['empty-action']" #action>
                  <slot name="empty-action" />
                </template>
              </ListViewState>
            </td>
          </tr>
        </tbody>

        <tbody v-else class="divide-y divide-outline-gray-1">
          <tr
            v-for="row in pageRows"
            :key="row.id"
            class="text-base text-ink-gray-8 transition-colors hover:bg-surface-gray-1"
            :class="row.getIsSelected() ? 'bg-surface-blue-1 hover:bg-surface-blue-1' : ''"
            @click="handleRowClick(row)"
          >
            <td
              v-for="cell in row.getVisibleCells()"
              :key="cell.id"
              class="h-14 px-4"
              :class="[
                alignClass(cell.column.columnDef.meta?.align),
                cell.column.columnDef.meta?.cellClass,
              ]"
              :style="{ width: `${cell.column.getSize()}px` }"
            >
              <FlexRender :render="cell.column.columnDef.cell" :props="cell.getContext()" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ListViewPagination
      v-if="showPagination"
      :page="pagination.pageIndex + 1"
      :page-count="table.getPageCount()"
      :page-size="pagination.pageSize"
      :can-previous="table.getCanPreviousPage()"
      :can-next="table.getCanNextPage()"
      @first="table.firstPage()"
      @previous="table.previousPage()"
      @next="table.nextPage()"
      @last="table.lastPage()"
      @page-size-change="table.setPageSize($event)"
    />
  </section>
</template>
