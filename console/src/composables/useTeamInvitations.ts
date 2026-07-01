import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { useBusyRunner } from '@/composables/useBusyRunner'
import { getErrorMessage } from '@/lib/toast'
import { submitOrThrow } from '@/lib/frappeCall'
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

whenTeamReady(() => invitationsCall.reload())

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
    invitations: computed<InvitationRow[]>(() => invitationsCall.data ?? []),
    loading: computed(() => invitationsCall.loading || !invitationsCall.isFinished),
    error: computed(() =>
      invitationsCall.error ? getErrorMessage(invitationsCall.error, "Couldn't load invitations.") : null,
    ),
    busy,
    reload: () => invitationsCall.reload(),
    resend,
    revoke,
  }
}
