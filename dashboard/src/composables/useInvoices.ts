import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage, isAbortError } from '@/lib/toast'
import type { InvoiceSummary } from '@/types/billing'

// The team's invoice list (list_invoices), shared by the Invoices page and
// global search so both read the one fetch instead of drifting apart.

const invoicesCall = useCall<InvoiceSummary[], { team: string }>({
	url: method(API.invoices),
	params: teamParams,
	immediate: false,
	refetch: true,
})

whenTeamReady(() => invoicesCall.reload())

export function useInvoices() {
	return {
		invoices: computed<InvoiceSummary[]>(() => invoicesCall.data ?? []),
		loading: computed(() => invoicesCall.loading),
		error: computed(() => {
			if (!invoicesCall.error || isAbortError(invoicesCall.error)) return null
			return getErrorMessage(invoicesCall.error, "Couldn't load invoices.")
		}),
		reload: () => invoicesCall.reload(),
	}
}
