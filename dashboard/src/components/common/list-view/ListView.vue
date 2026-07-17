<script setup lang="ts" generic="TData extends object">
import { computed, h, ref } from 'vue'
import { Button, Checkbox, Combobox, TextInput, Skeleton } from 'frappe-ui'
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
import Alert from '@/components/common/Alert.vue'
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
		/** Highlight the row whose rowKey matches this — for master/detail lists. */
		activeKey?: string | null
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
		activeKey: null,
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
	size: 1,
	minSize: 1,
	maxSize: 1,
	enableSorting: false,
	enableHiding: false,
	header: ({ table }) =>
		h(Checkbox, {
			class: 'cursor-pointer shrink-0',
			modelValue: table.getIsAllPageRowsSelected(),
			'aria-label': 'Select all rows on this page',
			'onUpdate:modelValue': (...args: unknown[]) =>
				table.toggleAllPageRowsSelected(Boolean(args[0])),
		}),
	cell: ({ row }) =>
		h(Checkbox, {
			class: 'cursor-pointer shrink-0',
			modelValue: row.getIsSelected(),
			disabled: !row.getCanSelect(),
			'aria-label': `Select row ${row.id}`,
			onClick: (event: Event) => event.stopPropagation(),
			'onUpdate:modelValue': (...args: unknown[]) =>
				row.toggleSelected(Boolean(args[0])),
		}),
}))

const tableColumns = computed(() =>
	props.selectable ? [selectionColumn.value, ...props.columns] : props.columns,
)

// TanStack state derived from the query model. These MUST be stable references:
// the sorted/filtered/paginated row models (active in client-side mode) memoize on
// them, so returning a fresh array/object on every read recomputes the models on
// every render and wedges the page in an update loop. `computed` memoizes — the
// reference changes only when the query actually does.
const sortingState = computed<SortingState>(() =>
	query.value.sort
		? [
				{
					id: query.value.sort.key,
					desc: query.value.sort.direction === 'desc',
				},
			]
		: [],
)
const columnFiltersState = computed<ColumnFiltersState>(() =>
	Object.entries(query.value.filters)
		.filter(([, value]) => value !== '')
		.map(([id, value]) => ({ id, value })),
)
const paginationState = computed<PaginationState>(() => ({
	pageIndex: query.value.page - 1,
	pageSize: query.value.pageSize,
}))

const table = useVueTable({
	get data() {
		return props.rows
	},
	get columns() {
		return tableColumns.value
	},
	getRowId: (row) => props.rowKey(row),
	// Keep tanstack from auto-resetting the page on every row-model recompute. Our
	// query handlers already reset `page` to 1 explicitly on search/filter/sort, so
	// auto-reset is redundant — and harmful: in a client-side list it fires
	// onPaginationChange while the rows re-render (e.g. when a master/detail
	// selection flips `activeKey`), which rewrites `query` mid-render and spins into
	// an infinite update loop that freezes the tab. Server-side lists dodge this
	// only because manualPagination already disables auto-reset.
	autoResetPageIndex: false,
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
			return sortingState.value
		},
		get globalFilter() {
			return query.value.search
		},
		get columnFilters() {
			return columnFiltersState.value
		},
		get pagination() {
			return paginationState.value
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
	() =>
		query.value.search !== '' ||
		Object.values(query.value.filters).some(Boolean),
)
const resultCount = computed(() =>
	props.serverSide ? props.totalRows : filteredRows.value.length,
)
const countText = computed(() => {
	const label =
		resultCount.value === 1 ? props.itemLabel : `${props.itemLabel}s`
	return `${resultCount.value.toLocaleString()} ${label}`
})
// Footer visibility deliberately ignores `loading`: a refetch (e.g. changing
// the page size) keeps the row count stable, so unmounting the footer mid-load
// only causes a flicker and layout shift. It stays put while new rows arrive.
const showPagination = computed(() => props.paginated && resultCount.value > 0)
const showFooter = computed(
	() => (props.showCount && resultCount.value > 0) || showPagination.value,
)
const pagination = computed(() => table.getState().pagination)
const gridTemplateColumns = computed(() =>
	table
		.getFlatHeaders()
		.map((header) =>
			header.id === '__selection' ? '14px' : `${header.getSize()}fr`,
		)
		.join(' '),
)

function clearFilters(): void {
	if (!hasActiveQuery.value && query.value.page === 1) return

	query.value = {
		...query.value,
		page: 1,
		search: '',
		filters: {},
	}
}

function updateFilter(key: string, value: unknown): void {
	const nextValue = typeof value === 'string' ? value : ''
	if (query.value.filters[key] === nextValue && query.value.page === 1) return

	query.value = {
		...query.value,
		page: 1,
		filters: {
			...query.value.filters,
			[key]: nextValue,
		},
	}
}

function updateSearch(updater: Updater<unknown>): void {
	const nextSearch = String(applyUpdater(updater, query.value.search) ?? '')
	if (query.value.search === nextSearch && query.value.page === 1) return

	query.value = { ...query.value, page: 1, search: nextSearch }
}

function updateSorting(updater: Updater<SortingState>): void {
	const current: SortingState = query.value.sort
		? [
				{
					id: query.value.sort.key,
					desc: query.value.sort.direction === 'desc',
				},
			]
		: []
	const next = applyUpdater(updater, current)[0]
	const nextSort: ListViewQuery['sort'] = next
		? { key: next.id, direction: next.desc ? 'desc' : 'asc' }
		: null
	if (sameSort(query.value.sort, nextSort) && query.value.page === 1) return

	query.value = {
		...query.value,
		page: 1,
		sort: nextSort,
	}
}

function updateColumnFilters(updater: Updater<ColumnFiltersState>): void {
	const current = Object.entries(query.value.filters).map(([id, value]) => ({
		id,
		value,
	}))
	const next = applyUpdater(updater, current)
	const nextFilters = Object.fromEntries(
		next.map(({ id, value }) => [id, String(value ?? '')]),
	)
	if (
		sameStringRecord(query.value.filters, nextFilters) &&
		query.value.page === 1
	)
		return

	query.value = {
		...query.value,
		page: 1,
		filters: nextFilters,
	}
}

function updatePagination(updater: Updater<PaginationState>): void {
	const next = applyUpdater(updater, pagination.value)
	const nextPage = next.pageIndex + 1
	if (query.value.page === nextPage && query.value.pageSize === next.pageSize)
		return

	query.value = {
		...query.value,
		page: nextPage,
		pageSize: next.pageSize,
	}
}

function sortAria(column: ReturnType<typeof table.getAllLeafColumns>[number]) {
	const sorted = column.getIsSorted()
	return sorted === 'asc'
		? 'ascending'
		: sorted === 'desc'
			? 'descending'
			: 'none'
}

function justifyClass(align?: 'start' | 'center' | 'end'): string {
	if (align === 'center') return 'justify-center'
	if (align === 'end') return 'justify-end'
	return 'justify-start'
}

function metaClass(className?: string): string {
	return className?.replace(/\btable-cell\b/g, 'block') ?? ''
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

function sameSort(
	current: ListViewQuery['sort'],
	next: ListViewQuery['sort'],
): boolean {
	if (!current || !next) return current === next
	return current.key === next.key && current.direction === next.direction
}

function sameStringRecord(
	current: Record<string, string>,
	next: Record<string, string>,
): boolean {
	const currentKeys = Object.keys(current)
	const nextKeys = Object.keys(next)
	return (
		currentKeys.length === nextKeys.length &&
		currentKeys.every((key) => current[key] === next[key])
	)
}

// Search + filters are only useful once there's data (or an active query). On a
// genuinely empty list they add noise, so hide them — the empty state + the
// #toolbar action carry the page instead.
const showListControls = computed(
	() =>
		(props.searchable || props.filters.length > 0) &&
		(hasRows.value || hasActiveQuery.value || props.loading),
)

defineExpose({ table })
</script>

<template>
	<section class="min-w-0">
		<div
			v-if="showListControls || $slots.toolbar"
			class="flex flex-wrap items-center justify-between gap-3 pb-3"
		>
			<div
				v-if="showListControls"
				class="flex min-w-0 flex-1 flex-wrap items-center gap-2"
			>
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
					label="Clear"
					variant="ghost"
					@click="clearFilters"
				/>
			</div>
			<div
				v-if="$slots.toolbar"
				class="ml-auto flex shrink-0 items-center gap-3"
			>
				<slot name="toolbar" :table="table" />
			</div>
		</div>

		<div
			v-if="selectable && table.getSelectedRowModel().rows.length"
			class="mb-2 flex flex-wrap items-center justify-between gap-3 rounded bg-surface-blue-1 px-3 py-2"
		>
			<p class="text-p-sm font-medium text-ink-blue-8">
				{{ table.getSelectedRowModel().rows.length }}
				selected
			</p>
			<div class="flex items-center gap-2">
				<slot
					name="selection-actions"
					:rows="table.getSelectedRowModel().rows.map((row) => row.original)"
					:clear="table.resetRowSelection"
				/>
				<Button
					label="Clear"
					variant="ghost"
					@click="table.resetRowSelection()"
				/>
			</div>
		</div>

		<Alert
			v-if="error && hasRows"
			theme="red"
			:title="error"
			:action="{ label: 'Retry', onClick: () => $emit('retry') }"
			class="mb-2"
		/>

		<!-- flex-1 is inert unless the caller makes the root section a flex column
         (class fall-through) to pin the pagination footer to the bottom. -->
		<div class="relative min-w-0 flex-1 overflow-x-auto">
			<div role="table" class="min-w-[720px]">
				<div
					v-if="hasRows || loading"
					role="row"
					class="grid h-10 items-center gap-4 border-b border-outline-gray-2 px-2"
					:style="{ gridTemplateColumns }"
				>
					<div
						v-for="header in table.getFlatHeaders()"
						:key="header.id"
						role="columnheader"
						:aria-sort="header.column.getCanSort() ? sortAria(header.column) : undefined"
						class="flex min-w-0 items-center gap-2 truncate text-sm text-ink-gray-5"
						:class="[
              header.id === '__selection' ? 'shrink-0' : justifyClass(header.column.columnDef.meta?.align),
              metaClass(header.column.columnDef.meta?.headerClass),
            ]"
					>
						<button
							v-if="!header.isPlaceholder && header.column.getCanSort()"
							type="button"
							class="inline-flex min-w-0 items-center gap-2 truncate outline-none hover:text-ink-gray-8 focus-visible:ring-2 focus-visible:ring-outline-blue-2"
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
  'size-3.5 shrink-0',
]"
								aria-hidden="true"
							/>
						</button>
						<FlexRender
							v-else-if="!header.isPlaceholder"
							:render="header.column.columnDef.header"
							:props="header.getContext()"
						/>
					</div>
				</div>

				<div v-if="loading && !hasRows" role="rowgroup">
					<div
						v-for="rowIndex in 5"
						:key="rowIndex"
						role="row"
						class="grid h-10 items-center gap-4 border-b border-outline-gray-1 px-2"
						:style="{ gridTemplateColumns }"
					>
						<div
							v-for="column in visibleColumnCount"
							:key="column"
							role="cell"
							class="min-w-0"
						>
							<Skeleton
								class="h-3 rounded"
								:class="column === 1 ? 'w-2/3' : 'w-1/2'"
							/>
						</div>
					</div>
				</div>

				<!-- State messages stay inside the table, so they're wrapped in a
             row/cell: every non-rowgroup child of role="table" must be a row. -->
				<div v-else-if="!hasRows" role="row">
					<div
						role="cell"
						:aria-colindex="1"
						:aria-colspan="visibleColumnCount"
					>
						<ListViewState
							v-if="error"
							kind="error"
							title="Couldn't load this list"
							:description="error"
							@retry="$emit('retry')"
						/>
						<ListViewState
							v-else-if="hasActiveQuery"
							kind="filtered"
							title="No matching results"
							description="Change or clear the filters to see more results."
							@clear="clearFilters"
						/>
						<ListViewState
							v-else
							kind="empty"
							:title="emptyState.title"
							:description="emptyState.description"
						>
							<template v-if="$slots['empty-action']" #action>
								<slot name="empty-action" />
							</template>
						</ListViewState>
					</div>
				</div>

				<div v-else role="rowgroup">
					<div
						v-for="row in pageRows"
						:key="row.id"
						role="row"
						class="grid h-10 cursor-default items-center gap-4 border-b border-outline-gray-1 px-2 text-sm transition-colors duration-150 ease-in-out hover:bg-surface-sidebar"
						:class="
              row.getIsSelected() || activeKey === row.id
                ? 'bg-surface-gray-2 hover:bg-surface-gray-3'
                : ''
            "
						:style="{ gridTemplateColumns }"
						@click="handleRowClick(row)"
					>
						<div
							v-for="(cell, cellIndex) in row.getVisibleCells()"
							:key="cell.id"
							role="cell"
							class="flex min-w-0 overflow-x-hidden"
							:class="[
  cell.column.id === '__selection'
    ? 'w-fit shrink-0 pe-2'
    : [
      cellIndex === (selectable ? 1 : 0) ? 'text-ink-gray-9' : 'text-ink-gray-7',
      justifyClass(cell.column.columnDef.meta?.align),
    ],
  metaClass(cell.column.columnDef.meta?.cellClass),
              ]"
							@click="cell.column.id === '__selection' ? $event.stopPropagation() : undefined"
						>
							<FlexRender
								:render="cell.column.columnDef.cell"
								:props="cell.getContext()"
							/>
						</div>
					</div>
				</div>
			</div>
		</div>

		<ListViewPagination
			v-if="showFooter"
			:paginated="showPagination"
			:show-count="showCount"
			:count-text="countText"
			:count-loading="countLoading"
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
