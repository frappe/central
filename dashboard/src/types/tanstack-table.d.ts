import type { RowData } from '@tanstack/vue-table'

declare module '@tanstack/table-core' {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: 'start' | 'center' | 'end'
		cellClass?: string
		headerClass?: string
	}
}

export {}
