import { dayjs, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { currencySymbol, money, plural } from '@/lib/format'
import type {
	PaymentAttempt,
	SpendHistory,
	Statement,
	TaxSummary,
} from '@/types/billing'

export const BILLING_REPORT_MONTHS = [
	{ label: '3 months', value: 3 },
	{ label: '6 months', value: 6 },
	{ label: '12 months', value: 12 },
]

export function useBillingReports() {
	const { activeTeam } = useSession()
	const months = ref(12)
	const fromDate = computed(() =>
		dayjs()
			.subtract(months.value - 1, 'month')
			.startOf('month')
			.format('YYYY-MM-DD'),
	)
	const history = useCall<SpendHistory, { team: string; months: number }>({
		url: method(API.spendHistory),
		params: () => ({ team: activeTeam.value!, months: months.value }),
		immediate: false,
		refetch: true,
	})
	const statement = useCall<Statement, { team: string; from_date: string }>({
		url: method(API.statement),
		params: () => ({ team: activeTeam.value!, from_date: fromDate.value }),
		immediate: false,
		refetch: true,
	})
	const tax = useCall<TaxSummary, { team: string; from_date: string }>({
		url: method(API.taxSummary),
		params: () => ({ team: activeTeam.value!, from_date: fromDate.value }),
		immediate: false,
		refetch: true,
	})
	const attempts = useCall<PaymentAttempt[], { team: string; limit: number }>({
		url: method(API.paymentAttempts),
		params: () => ({ team: activeTeam.value!, limit: 1000 }),
		immediate: false,
		refetch: true,
	})

	function reload(): void {
		history.reload()
		statement.reload()
		tax.reload()
		attempts.reload()
	}
	whenTeamReady(reload)

	const currency = computed(() => history.data?.currency ?? 'INR')
	const average = computed(() => {
		const billed = (history.data?.months ?? []).filter(
			(month) => month.total > 0,
		)
		return billed.length
			? billed.reduce((sum, month) => sum + month.total, 0) / billed.length
			: 0
	})
	const taxCaption = computed(() => {
		const data = tax.data
		if (!data) return ''
		if (data.total_withheld > 0)
			return `plus ${money(data.total_withheld, data.currency)} withheld at source`
		if ((data.total_tax ?? 0) <= 0) return 'none charged in this period'
		const charged = data.by_type.filter(
			(row) => row.tax_type !== 'No tax' && row.tax_type !== 'Zero-rated',
		)
		if (charged.length === 1)
			return `${charged[0].tax_type} on ${money(charged[0].taxable, data.currency)}`
		return `across ${charged.length} tax types`
	})
	const hasDebt = computed(() => {
		const data = statement.data
		return data
			? Number(data.closing_outstanding ?? 0) +
					Number(data.opening_outstanding ?? 0) >
					0
			: false
	})
	const loading = computed(() => history.loading && !history.data)
	const neverBilled = computed(
		() =>
			!loading.value &&
			Boolean(history.data) &&
			months.value === 12 &&
			history.data?.invoice_count === 0 &&
			!hasDebt.value,
	)
	function exportUrl(report: string): string {
		const team = encodeURIComponent(activeTeam.value ?? '')
		return `/api/method/${API.exportCsv}?report=${report}&team=${team}&from_date=${fromDate.value}`
	}

	return {
		months,
		fromDate,
		history,
		statement,
		tax,
		attempts,
		currency,
		symbol: computed(() => currencySymbol(currency.value)),
		creditsSymbol: computed(() =>
			currencySymbol(statement.data?.currency ?? currency.value),
		),
		taxSymbol: computed(() =>
			currencySymbol(tax.data?.currency ?? currency.value),
		),
		average,
		invoiceCaption: computed(
			() => `across ${plural(history.data?.invoice_count ?? 0, 'invoice')}`,
		),
		taxCaption,
		loading,
		statementLoading: computed(() => statement.loading && !statement.data),
		taxLoading: computed(() => tax.loading && !tax.data),
		neverBilled,
		exportUrl,
		reload,
	}
}
