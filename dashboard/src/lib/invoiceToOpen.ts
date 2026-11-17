import type { StatementRow } from '@/types/billing'

type OpenRowFields = Pick<
	StatementRow,
	'invoice' | 'status' | 'is_issued' | 'period_start'
>

/** The owed invoice to show first: an overdue one, otherwise the oldest open one. */
export function invoiceToOpen(rows: readonly OpenRowFields[]): string | null {
	// An invoice not issued yet is still being prepared, so nothing is owed on it.
	const open = rows.filter(
		(row) =>
			row.is_issued &&
			(row.status === 'Outstanding' || row.status === 'Overdue'),
	)
	open.sort(
		(a, b) =>
			Number(b.status === 'Overdue') - Number(a.status === 'Overdue') ||
			a.period_start.localeCompare(b.period_start),
	)
	return open[0]?.invoice ?? null
}
