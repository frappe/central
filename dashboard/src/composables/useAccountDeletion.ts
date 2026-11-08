import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import type {
	ArchiveCheck,
	CreditBalance,
} from '@/composables/useTeamArchiveChecks'
import { getErrorMessage } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'

export interface OwnedTeam {
	team: string
	team_name: string
	checks: ArchiveCheck[]
	credit_balances: CreditBalance[]
}

export interface DeletionRequest {
	name: string
	status: 'Pending Verification' | 'Pending Approval'
	delete_after: string | null
}

interface AccountDeletion {
	teams: OwnedTeam[]
	request: DeletionRequest | null
}

const statusCall = useCall<AccountDeletion>({
	url: method(API.accountDeletion),
	immediate: false,
})
const deleteCall = useCall<{ request: DeletionRequest }, { email: string }>({
	url: method(API.deleteAccount),
	method: 'POST',
	immediate: false,
})
const cancelCall = useCall<{ request: null }, Record<string, never>>({
	url: method(API.cancelAccountDeletion),
	method: 'POST',
	immediate: false,
})

export function useAccountDeletion() {
	const teams = computed<OwnedTeam[]>(() => statusCall.data?.teams ?? [])

	return {
		teams,
		request: computed(() => statusCall.data?.request ?? null),
		loading: computed(() => statusCall.loading),
		error: computed(() =>
			statusCall.error
				? getErrorMessage(statusCall.error, "We couldn't check your account.")
				: '',
		),
		isClear: computed(
			() =>
				statusCall.data != null &&
				teams.value.every((team) => team.checks.every((check) => check.passed)),
		),
		saving: computed(() => deleteCall.loading || cancelCall.loading),
		reload: () => statusCall.reload(),
		async deleteAccount(email: string): Promise<void> {
			await submitOrThrow(deleteCall, { email })
			await statusCall.reload()
		},
		async cancel(): Promise<void> {
			await submitOrThrow(cancelCall, {})
			await statusCall.reload()
		},
	}
}
