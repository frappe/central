<script setup lang="ts" generic="TData extends object">
import { Alert, Button, Select, Skeleton, TextInput } from 'frappe-ui'
import {
	List,
	ListCell,
	ListHeader,
	ListHeaderCell,
	ListHeaderCellSort,
	ListRow,
	ListRows,
} from 'frappe-ui/list'
import { computed, getCurrentInstance, ref } from 'vue'
import ListViewPagination from './ListViewPagination.vue'
import ListViewState from './ListViewState.vue'
import {
	createListViewQuery,
	type ListViewColumn,
	type ListViewEmptyState,
	type ListViewFilter,
	type ListViewQuery,
} from './types'

const props = withDefaults(
	defineProps<{
		rows: TData[]
		columns: ListViewColumn<TData>[]
		rowKey: (row: TData) => string
		loading?: boolean
		error?: string | null
		searchable?: boolean
		searchPlaceholder?: string
		filters?: ListViewFilter[]
		selectable?: boolean
		paginated?: boolean
		/** Hide the 10/20/50 choice when the page owns the page size. */
		showPageSize?: boolean
		serverSide?: boolean
		totalRows?: number
		countLoading?: boolean
		itemLabel?: string
		showCount?: boolean
		emptyState?: ListViewEmptyState
		rowClass?: string
		activeKey?: string | null
		/**
		 * True while a page-owned #filters control (e.g. a date range) is
		 * narrowing the rows it passes in, so an empty result reads as "no
		 * matching results", not as a genuinely empty list. Pair with
		 * @clear-filters to reset that control.
		 */
		externalFilterActive?: boolean
	}>(),
	{
		loading: false,
		error: null,
		searchable: false,
		searchPlaceholder: 'Search…',
		filters: () => [],
		selectable: false,
		paginated: true,
		showPageSize: true,
		serverSide: false,
		totalRows: 0,
		countLoading: false,
		itemLabel: 'row',
		showCount: true,
		rowClass: 'min-h-10',
		activeKey: null,
		externalFilterActive: false,
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
	/** Fired by the filtered empty state's Clear so pages reset their #filters controls too. */
	clearFilters: []
}>()

const selection = ref<string[]>([])

const readValue = (row: TData, column: ListViewColumn<TData>): unknown =>
	column.value
		? column.value(row)
		: (row as Record<string, unknown>)[column.key]

const includesText = (value: unknown, text: string): boolean =>
	value != null && String(value).toLowerCase().includes(text.toLowerCase())

const compareValues = (a: unknown, b: unknown): number => {
	if (typeof a === 'number' && typeof b === 'number') return a - b
	return String(a ?? '').localeCompare(String(b ?? ''), undefined, {
		numeric: true,
	})
}

const columnsByKey = computed(
	() => new Map(props.columns.map((column) => [column.key, column])),
)

const isShown = (row: TData): boolean => {
	const search = query.value.search.trim()
	const matchesSearch =
		!search ||
		props.columns.some((column) => includesText(readValue(row, column), search))

	return (
		matchesSearch &&
		Object.entries(query.value.filters).every(([key, value]) => {
			const column = columnsByKey.value.get(key)
			return !value || (!!column && includesText(readValue(row, column), value))
		})
	)
}

const filteredRows = computed(() =>
	props.serverSide ? props.rows : props.rows.filter(isShown),
)

const sortedRows = computed(() => {
	const sort = query.value.sort
	const column = sort && columnsByKey.value.get(sort.key)
	if (props.serverSide || !sort || !column) return filteredRows.value

	const compare =
		column.compare ??
		((a: TData, b: TData) =>
			compareValues(readValue(a, column), readValue(b, column)))
	const direction = sort.direction === 'asc' ? 1 : -1

	return [...filteredRows.value].sort((a, b) => compare(a, b) * direction)
})

const pageRows = computed(() => {
	if (!props.paginated || props.serverSide) return sortedRows.value

	const start = (query.value.page - 1) * query.value.pageSize
	return sortedRows.value.slice(start, start + query.value.pageSize)
})

const hasRows = computed(() => props.rows.length > 0)
const hasActiveQuery = computed(
	() =>
		query.value.search !== '' ||
		Object.values(query.value.filters).some(Boolean),
)
const resultCount = computed(() =>
	props.serverSide ? props.totalRows : filteredRows.value.length,
)
const pageCount = computed(() =>
	Math.ceil(resultCount.value / query.value.pageSize),
)
const countText = computed(() => {
	const label =
		resultCount.value === 1 ? props.itemLabel : `${props.itemLabel}s`
	return `${resultCount.value.toLocaleString()} ${label}`
})

const showPagination = computed(
	() => props.paginated && resultCount.value > 0 && pageCount.value > 1,
)
// A short list is counted at a glance, so the count only shows from this size.
const MINIMUM_ROWS_FOR_COUNT = 5
const showCountText = computed(
	() => props.showCount && resultCount.value >= MINIMUM_ROWS_FOR_COUNT,
)
const showFooter = computed(() => showCountText.value || showPagination.value)

const selectedRows = computed(() => {
	const keys = new Set(selection.value)
	return props.rows.filter((row) => keys.has(props.rowKey(row)))
})
const hasSelection = computed(
	() => props.selectable && selectedRows.value.length > 0,
)
const clearSelection = (): void => {
	selection.value = []
}

const gridColumns = computed(() =>
	props.columns.map((column) => column.width ?? 'minmax(0,1fr)'),
)

const isSkeleton = computed(() => props.loading && !hasRows.value)
const stateKind = computed(() => {
	if (props.error && !hasRows.value) return 'error'
	if (hasActiveQuery.value || props.externalFilterActive || hasRows.value)
		return 'filtered'
	return 'empty'
})

const instance = getCurrentInstance()
const interactive = computed(() => !!instance?.vnode.props?.onRowClick)

const updateQuery = (patch: Partial<ListViewQuery>): void => {
	query.value = { ...query.value, page: 1, ...patch }
}

const setSearch = (value: unknown): void => {
	const search = String(value ?? '')
	if (search !== query.value.search) updateQuery({ search })
}

const setFilter = (key: string, value: unknown): void => {
	const next = typeof value === 'string' ? value : ''
	if (query.value.filters[key] === next) return

	updateQuery({ filters: { ...query.value.filters, [key]: next } })
}

const getSortDirection = (column: ListViewColumn<TData>) =>
	query.value.sort?.key === column.key ? query.value.sort.direction : null

const toggleSort = (column: ListViewColumn<TData>): void => {
	const direction = getSortDirection(column)
	const next = direction === null ? 'asc' : direction === 'asc' ? 'desc' : null

	updateQuery({
		sort: next ? { key: column.key, direction: next } : null,
	})
}

const setPage = (page: number): void => {
	query.value = { ...query.value, page }
}

const clearFilters = (): void => {
	// The page owns its #filters controls, so clearing those is delegated up.
	emit('clearFilters')
	if (hasActiveQuery.value || query.value.page !== 1)
		updateQuery({ search: '', filters: {} })
}

const showListControls = computed(
	() => props.searchable || props.filters.length > 0,
)
</script>

<template>
	<section class="min-w-0">
		<div
			v-if="showListControls || $slots.toolbar || $slots['controls-start'] || hasSelection"
			class="flex flex-wrap items-center justify-between gap-3 pb-3"
		>
			<!-- Selection takes over the controls row, so the table never shifts. -->
			<div
				v-if="hasSelection"
				class="flex min-w-0 flex-1 items-center justify-between gap-3"
			>
				<p class="text-sm-medium text-ink-gray-8 tabular-nums">
					{{ selectedRows.length }}
					selected
				</p>

				<div class="flex items-center gap-2">
					<slot
						name="selection-actions"
						:rows="selectedRows"
						:clear="clearSelection"
					/>
					<Button label="Clear" variant="ghost" @click="clearSelection" />
				</div>
			</div>

			<div
				v-else-if="showListControls || $slots['controls-start']"
				class="flex min-w-0 flex-1 flex-wrap items-center gap-2"
			>
				<slot name="controls-start" />

				<TextInput
					v-if="searchable"
					:model-value="query.search"
					class="w-full sm:w-80"
					:placeholder="searchPlaceholder"
					:debounce="250"
					@update:model-value="setSearch"
				>
					<template #prefix>
						<span class="lucide-search size-4" aria-hidden="true" />
					</template>
				</TextInput>

				<Select
          side='bottom'
					v-for="filter in filters"
					:key="filter.key"
					:model-value="query.filters[filter.key] || ''"
					class="w-40"
					:placeholder="filter.allLabel || `All ${filter.label.toLowerCase()}`"
					:options="[
						{ label: filter.allLabel || `All ${filter.label.toLowerCase()}`, value: '' },
						...filter.options,
					]"
					@update:model-value="setFilter(filter.key, $event)"
				>
					<template
						v-if="filter.options.some((option) => option.dot)"
						#item-prefix="{ item }"
					>
						<span
							class="size-2 shrink-0 rounded-full"
							:style="{ background: item.dot || 'var(--ink-gray-4)' }"
						/>
					</template>
				</Select>

				<slot name="filters" />
			</div>

			<div
				v-if="$slots.toolbar"
				class="ml-auto flex shrink-0 items-center gap-3"
			>
				<slot name="toolbar" />
			</div>
		</div>

		<Alert
			v-if="error && hasRows"
			theme="red"
			:title="error"
			:primary-action="{ label: 'Retry', onClick: () => $emit('retry') }"
			class="mb-2"
		/>

		<!-- flex-1 is inert unless the caller makes the root section a flex column
		     to pin the pagination footer to the bottom. -->
		<div
			v-if="isSkeleton || pageRows.length"
			class="min-w-0 flex-1 overflow-x-auto"
		>
			<List
				v-model:selection="selection"
				class="min-w-[720px] list-gap-4 list-row-px-2"
				:columns="gridColumns"
				:selectable="selectable"
			>
				<ListHeader>
					<template v-for="column in columns" :key="column.key">
						<ListHeaderCellSort
							v-if="column.sortable"
							:class="column.class"
							:direction="getSortDirection(column)"
							:align="column.align"
							@click="toggleSort(column)"
						>
							{{ column.label }}
						</ListHeaderCellSort>
						<ListHeaderCell
							v-else
							:class="[column.class, column.align === 'end' && 'justify-end']"
						>
							{{ column.label }}
						</ListHeaderCell>
					</template>
				</ListHeader>

				<template v-if="isSkeleton">
					<ListRow v-for="index in 5" :key="index" :class="rowClass">
						<ListCell
							v-for="(column, columnIndex) in columns"
							:key="column.key"
							:class="column.class"
						>
							<Skeleton
								class="h-3 rounded-4"
								:class="columnIndex === 0 ? 'w-2/3' : 'w-1/2'"
							/>
						</ListCell>
					</ListRow>
				</template>

				<ListRows
					v-else
					v-slot="{ item, value }"
					:items="pageRows"
					:row-key="rowKey"
				>
					<ListRow
						:value="value"
						:aria-current="value === activeKey || undefined"
						:class="[
							rowClass,
							interactive && 'cursor-pointer rounded-5 hover:bg-surface-gray-2',
							value === activeKey && 'bg-surface-gray-3',
						]"
					>
						<button
							v-if="interactive"
							type="button"
							class="absolute inset-0 rounded-5"
							:aria-label="`Open ${readValue(item, columns[0])}`"
							@click="emit('rowClick', item)"
						/>

						<ListCell
							v-for="(column, columnIndex) in columns"
							:key="column.key"
							class="text-sm"
							:class="[
								column.class,
								column.align === 'end' && 'justify-end',
								columnIndex === 0 ? 'text-ink-gray-9' : 'text-ink-gray-7',
							]"
						>
							<slot
								:name="column.key"
								:row="item as TData"
								:value="readValue(item, column)"
							>
								<span class="truncate">{{ readValue(item, column) }}</span>
							</slot>
						</ListCell>
					</ListRow>
				</ListRows>
			</List>
		</div>

		<ListViewState
			v-else-if="stateKind === 'error'"
			kind="error"
			title="Couldn't load this list"
			:description="error ?? undefined"
			@retry="$emit('retry')"
		/>
		<ListViewState
			v-else-if="stateKind === 'filtered'"
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

		<ListViewPagination
			v-if="showFooter"
			:paginated="showPagination"
			:show-page-size="showPageSize"
			:show-count="showCountText"
			:count-text="countText"
			:count-loading="countLoading"
			:page="query.page"
			:page-count="pageCount"
			:page-size="query.pageSize"
			:can-previous="query.page > 1"
			:can-next="query.page < pageCount"
			@first="setPage(1)"
			@previous="setPage(query.page - 1)"
			@next="setPage(query.page + 1)"
			@last="setPage(pageCount)"
			@page-size-change="updateQuery({ pageSize: $event })"
		/>
	</section>
</template>
