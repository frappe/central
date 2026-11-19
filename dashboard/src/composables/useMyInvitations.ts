import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type { MyInvitation } from '@/types/api'

// The signed-in user's pending invitations across teams. A module singleton, so the
// app menu badge and the Invitations settings tab share one fetch. Accepting also
// re-pulls the session and capabilities so the joined team appears in the switcher.

// immediate:false keeps the request out of module import; the first consumer loads it.
const invitationsCall = useCall<MyInvitation[]>({
	url: method(API.myInvitations),
	immediate: false,
})

const acceptCall = useCall<
	{ team: string; role: string },
	{ invitation: string }
>({
	url: method(API.acceptInvitation),
	method: 'POST',
	immediate: false,
})
const declineCall = useCall<{ declined: boolean }, { invitation: string }>({
	url: method(API.declineInvitation),
	method: 'POST',
	immediate: false,
})

const busy = ref<string>('')

export function useMyInvitations() {
	// Load on first use (component setup), not at import. Guarded so the shared
	// singleton fetches once even when several consumers mount together.
	if (!invitationsCall.data && !invitationsCall.loading)
		invitationsCall.reload()

	const session = useSession()
	const caps = useCapabilities()

	async function accept(invitation: MyInvitation): Promise<void> {
		busy.value = invitation.name
		try {
			await submitOrThrow(acceptCall, { invitation: invitation.name })
			successToast(`You joined ${invitation.team_name}`)
			await session.reload()
			session.setActiveTeam(invitation.team)
			caps.reload()
			invitationsCall.reload()
		} catch (e) {
			reportError(e)
		} finally {
			busy.value = ''
		}
	}

	async function decline(invitation: MyInvitation): Promise<void> {
		busy.value = invitation.name
		try {
			await submitOrThrow(declineCall, { invitation: invitation.name })
			successToast(`Declined the invite to ${invitation.team_name}`)
			invitationsCall.reload()
		} catch (e) {
			reportError(e)
		} finally {
			busy.value = ''
		}
	}

	return {
		invitations: computed<MyInvitation[]>(() => invitationsCall.data ?? []),
		count: computed<number>(() => invitationsCall.data?.length ?? 0),
		loading: computed(() => invitationsCall.loading),
		error: computed(() =>
			invitationsCall.error
				? getErrorMessage(
						invitationsCall.error,
						"Invitations couldn't be loaded.",
					)
				: '',
		),
		busy,
		reload: () => invitationsCall.reload(),
		accept,
		decline,
	}
}
