import type { ColumnDef, RowData, Table } from '@tanstack/vue-table'

export type ListViewColumn<TData extends RowData> = ColumnDef<TData, unknown>
export type ListViewTable<TData extends RowData> = Table<TData>

export interface ListViewEmptyState {
  title: string
  description?: string
}

export interface ListViewFilterOption {
  label: string
  value: string
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

export function createListViewQuery(
  overrides: Partial<ListViewQuery> = {},
): ListViewQuery {
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
