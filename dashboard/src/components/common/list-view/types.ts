export interface ListViewColumn<TData> {
	key: string
	label: string
	width?: string
	value?: (row: TData) => unknown
	sortable?: boolean
	compare?: (a: TData, b: TData) => number
	align?: 'start' | 'end'
	class?: string
}

export interface ListViewEmptyState {
	title: string
	description?: string
}

export interface ListViewFilterOption {
	label: string
	value: string
	dot?: string
}

export interface ListViewFilter {
	key: string
	label: string
	allLabel?: string
	options: ListViewFilterOption[]
}

export interface ListViewSort {
	key: string
	direction: 'asc' | 'desc'
}

export interface ListViewQuery {
	page: number
	pageSize: number
	search: string
	sort: ListViewSort | null
	filters: Record<string, string>
}

export const createListViewQuery = (
	overrides: Partial<ListViewQuery> = {},
): ListViewQuery => {
	const { filters = {}, ...rest } = overrides
	return {
		page: 1,
		pageSize: 10,
		search: '',
		sort: null,
		...rest,
		filters: { ...filters },
	}
}
