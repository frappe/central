import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { teamParams } from '@/composables/useTeamScope'
import { getErrorMessage } from '@/lib/feedback'

export type ArchiveCheckKey =
	| 'servers'
	| 'snapshots'
	| 'buckets'
	| 'add_ons'
	| 'invoices'
	| 'final_bill'

export interface ArchiveCheck {
	key: ArchiveCheckKey
	passed: boolean
	count: number
}

export interface CreditBalance {
	currency: string
	balance: number
}

interface ArchiveChecks {
	checks: ArchiveCheck[]
	credit_balances: CreditBalance[]
}

// What still stops the active team from being archived, and the credit it would lose.
// The archive dialog loads it when it opens and again when the owner comes back.
const checksCall = useCall<ArchiveChecks, { team: string }>({
	url: method(API.teamArchiveChecks),
	params: teamParams,
	immediate: false,
})

export function useTeamArchiveChecks() {
	return {
		checks: computed<ArchiveCheck[]>(() => checksCall.data?.checks ?? []),
		creditBalances: computed<CreditBalance[]>(
			() => checksCall.data?.credit_balances ?? [],
		),
		loading: computed(() => checksCall.loading),
		error: computed(() =>
			checksCall.error
				? getErrorMessage(checksCall.error, "We couldn't check this team.")
				: '',
		),
		isClear: computed(
			() =>
				checksCall.data != null &&
				checksCall.data.checks.every((check) => check.passed),
		),
		reload: () => checksCall.reload(),
	}
}
