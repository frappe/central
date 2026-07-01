import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { successToast, errorToast, getErrorMessage } from '@/lib/toast'
import type { MemberStatus, TeamMemberRow } from '@/types/api'

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

type RoleParams = { team: string; user: string; role: string }
type StatusParams = { team: string; user: string; status: MemberStatus }
type RemoveParams = { team: string; user: string }

const setRoleCall = useCall<unknown, RoleParams>({ url: method(API.setTeamMemberRole), method: 'POST', immediate: false })
const setStatusCall = useCall<unknown, StatusParams>({ url: method(API.setTeamMemberStatus), method: 'POST', immediate: false })
const removeCall = useCall<unknown, RemoveParams>({ url: method(API.removeTeamMember), method: 'POST', immediate: false })

const busy = ref<string>('')

export function useTeamMembers() {
  async function run(fn: () => Promise<unknown>, ok: string, user: string): Promise<void> {
    busy.value = user
    try {
      await fn()
      successToast(ok)
      membersCall.reload()
    } catch (e) {
      errorToast(e)
    } finally {
      busy.value = ''
    }
  }

  function setRole(user: string, role: string) {
    return run(
      () => submitOrThrow(setRoleCall, { team: teamParams().team, user, role }),
      `Updated ${user}'s role.`,
      user,
    )
  }

  function setStatus(user: string, status: MemberStatus) {
    const verb = status === 'Suspended' ? 'Suspended' : 'Reactivated'
    return run(
      () => submitOrThrow(setStatusCall, { team: teamParams().team, user, status }),
      `${verb} ${user}.`,
      user,
    )
  }

  function remove(user: string) {
    return run(
      () => submitOrThrow(removeCall, { team: teamParams().team, user }),
      `Removed ${user} from the team.`,
      user,
    )
  }

  return {
    members: computed<TeamMemberRow[]>(() => membersCall.data ?? []),
    loading: computed(() => membersCall.loading || !membersCall.isFinished),
    error: computed(() =>
      membersCall.error ? getErrorMessage(membersCall.error, "Couldn't load members.") : null,
    ),
    busy,
    reload: () => membersCall.reload(),
    setRole,
    setStatus,
    remove,
  }
}

async function submitOrThrow<TParams extends object>(
  call: { submit: (params: TParams) => Promise<unknown>; error: unknown },
  params: TParams,
): Promise<void> {
  await call.submit(params)
  if (call.error) throw call.error
}
