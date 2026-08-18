import { useCall } from 'frappe-ui'
import { computed, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBusyRunner } from '@/composables/useBusyRunner'
import { useCapabilities } from '@/composables/useCapabilities'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { submitOrThrow } from '@/lib/frappeCall'
import { getErrorMessage, isAbortError } from '@/lib/toast'
import type { InvitationRow } from '@/types/api'

// The active team's invitations — the manager's view (gated server-side on
// team:manage_members). Resend extends the expiry and re-emails; revoke kills a
// pending invite. One invitation mutates at a time; `busy` holds its name.

const invitationsCall = useCall<InvitationRow[], { team: string }>({
	url: method(API.listTeamInvitations),
	params: teamParams,
	refetch: true,
	immediate: false,
})

// The roster shows pending invites inline, so this module now loads on the Teams
// page for everyone. list_team_invitations is gated on team:manage_members, so
// wait for the capability rather than firing a request a viewer can only 403 on.
const { canManageMembers } = useCapabilities()
whenTeamReady(() => {
	if (canManageMembers.value) invitationsCall.reload()
})
watch(canManageMembers, (can, was) => {
	if (can && !was) invitationsCall.reload()
})

// Losing the capability — a demotion, or a switch to a team you don't manage —
// has to take the fetched rows with it: they carry invitees' email addresses,
// roles and resource scopes, and this call's data outlives any one page. Every
// read below is gated on the live capability rather than on what was fetched
// while it still held.

const resendCall = useCall<{ expires_on: string }, { invitation: string }>({
	url: method(API.resendInvitation),
	method: 'POST',
	immediate: false,
})
const revokeCall = useCall<{ revoked: boolean }, { invitation: string }>({
	url: method(API.revokeInvitation),
	method: 'POST',
	immediate: false,
})

const { busy, run } = useBusyRunner()

export function useTeamInvitations() {
	function resend(invitation: InvitationRow) {
		return run(
			() => submitOrThrow(resendCall, { invitation: invitation.name }),
			`Resent invite to ${invitation.email}.`,
			invitation.name,
			() => invitationsCall.reload(),
		)
	}

	function revoke(invitation: InvitationRow) {
		return run(
			() => submitOrThrow(revokeCall, { invitation: invitation.name }),
			`Revoked invite to ${invitation.email}.`,
			invitation.name,
			() => invitationsCall.reload(),
		)
	}

	return {
		invitations: computed<InvitationRow[]>(() =>
			canManageMembers.value ? (invitationsCall.data ?? []) : [],
		),
		loading: computed(
			() =>
				canManageMembers.value &&
				(invitationsCall.loading || !invitationsCall.isFinished),
		),
		error: computed(() => {
			if (!canManageMembers.value) return null
			if (!invitationsCall.error || isAbortError(invitationsCall.error))
				return null
			return getErrorMessage(
				invitationsCall.error,
				"Couldn't load invitations.",
			)
		}),
		busy,
		reload: () => {
			if (canManageMembers.value) invitationsCall.reload()
		},
		resend,
		revoke,
	}
}
