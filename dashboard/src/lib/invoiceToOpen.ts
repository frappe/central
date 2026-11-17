import type { InvoiceSummary } from '@/types/billing'

type OpenRowFields = Pick<
	InvoiceSummary,
	'name' | 'status' | 'due_date' | 'period_start'
>

/** The owed invoice to show first: an overdue one, otherwise the oldest open one. */
export function invoiceToOpen(rows: readonly OpenRowFields[]): string | null {
	// An invoice gets a due date when it is issued. Before that it is still
	// being prepared, so nothing is owed on it.
	const open = rows.filter(
		(row) =>
			row.due_date &&
			(row.status === 'Outstanding' || row.status === 'Overdue'),
	)
	open.sort(
		(a, b) =>
			Number(b.status === 'Overdue') - Number(a.status === 'Overdue') ||
			a.period_start.localeCompare(b.period_start),
	)
	return open[0]?.name ?? null
}
