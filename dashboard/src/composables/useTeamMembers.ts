import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { useBusyRunner } from '@/composables/useBusyRunner'
import { getErrorMessage } from '@/lib/toast'
import { submitOrThrow } from '@/lib/frappeCall'
import type { MemberStatus, TeamMemberRoleAssignment, TeamMemberRow } from '@/types/api'

// The active team's roster plus the member mutations Central enforces:
// set role / suspend-activate / remove, each gated on team:manage_members server
// side (the UI mirrors the gate via useCapabilities). One member mutates at a
// time; `busy` holds its user id so its row can show a spinner.

const membersCall = useCall<TeamMemberRow[], { team: string }>({
	url: method(API.listTeamMembers),
	params: teamParams,
	refetch: true,
	immediate: false,
})

whenTeamReady(() => membersCall.reload())

type RolesParams = { team: string; user: string; roles: TeamMemberRoleAssignment[] }
type StatusParams = { team: string; user: string; status: MemberStatus }
type RemoveParams = { team: string; user: string }

const setRolesCall = useCall<unknown, RolesParams>({
	url: method(API.setTeamMemberRoles),
	method: 'POST',
	immediate: false,
})
const setStatusCall = useCall<unknown, StatusParams>({
	url: method(API.setTeamMemberStatus),
	method: 'POST',
	immediate: false,
})
const removeCall = useCall<unknown, RemoveParams>({
	url: method(API.removeTeamMember),
	method: 'POST',
	immediate: false,
})

const { busy, run } = useBusyRunner()

export function useTeamMembers() {
	const setRoles = (user: string, roles: TeamMemberRoleAssignment[]) =>
		run(
			() => submitOrThrow(setRolesCall, { team: teamParams().team, user, roles }),
			`Updated ${user}'s roles.`,
			user,
			() => membersCall.reload(),
		)

	function setStatus(user: string, status: MemberStatus) {
		const verb = status === 'Suspended' ? 'Suspended' : 'Reactivated'
		return run(
			() =>
				submitOrThrow(setStatusCall, { team: teamParams().team, user, status }),
			`${verb} ${user}.`,
			user,
			() => membersCall.reload(),
		)
	}

	function remove(user: string) {
		return run(
			() => submitOrThrow(removeCall, { team: teamParams().team, user }),
			`Removed ${user} from the team.`,
			user,
			() => membersCall.reload(),
		)
	}

	return {
		members: computed<TeamMemberRow[]>(() => membersCall.data ?? []),
		loading: computed(() => membersCall.loading || !membersCall.isFinished),
		error: computed(() =>
			membersCall.error
				? getErrorMessage(membersCall.error, "Couldn't load members.")
				: null,
		),
		busy,
		reload: () => membersCall.reload(),
		setRoles,
		setStatus,
		remove,
	}
}
