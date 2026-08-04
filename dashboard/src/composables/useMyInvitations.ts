import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { errorToast, successToast } from '@/lib/toast'
import type { MyInvitation } from '@/types/api'

// The signed-in user's pending invitations across teams — the invitee's inbox.
// A module singleton so the header badge and the inbox page share one fetch, and
// accepting/declining re-drives both. Accepting also re-pulls the team roster +
// capabilities so the newly joined team appears in the switcher immediately.

// immediate:false so the request doesn't fire at module-import time (this module
// is imported by AppShell, on every authenticated page). The first consumer
// triggers the load inside useMyInvitations(), i.e. in component setup.
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
			await acceptCall.submit({ invitation: invitation.name })
			if (acceptCall.error) throw acceptCall.error
			successToast(`You joined ${invitation.team_name}.`)
			await session.reload()
			session.setActiveTeam(invitation.team)
			caps.reload()
			invitationsCall.reload()
		} catch (e) {
			errorToast(e)
		} finally {
			busy.value = ''
		}
	}

	async function decline(invitation: MyInvitation): Promise<void> {
		busy.value = invitation.name
		try {
			await declineCall.submit({ invitation: invitation.name })
			if (declineCall.error) throw declineCall.error
			successToast(`Declined the invite to ${invitation.team_name}.`)
			invitationsCall.reload()
		} catch (e) {
			errorToast(e)
		} finally {
			busy.value = ''
		}
	}

	return {
		invitations: computed<MyInvitation[]>(() => invitationsCall.data ?? []),
		count: computed<number>(() => invitationsCall.data?.length ?? 0),
		loading: computed(() => invitationsCall.loading),
		busy,
		reload: () => invitationsCall.reload(),
		accept,
		decline,
	}
}
