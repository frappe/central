import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { successToast, errorToast, getErrorMessage } from '@/lib/toast'
import { submitOrThrow } from '@/lib/frappeCall'
import type { CapabilityInfo, TeamRoleRow } from '@/types/api'

// Roles available on the active team (system + this team's custom roles), each
// with the capabilities it grants, plus the full capability palette the role
// builder picks from. Module-level singletons so the Members and Roles screens
// share one fetch and a single role mutation re-drives both.

const rolesCall = useCall<TeamRoleRow[], { team: string }>({
  url: method(API.listTeamRoles),
  params: teamParams,
  refetch: true,
  immediate: false,
})

// The palette is team-independent — every capability in the system.
const capabilitiesCall = useCall<CapabilityInfo[]>({
  url: method(API.listCapabilities),
  immediate: false,
})

whenTeamReady(() => rolesCall.reload())

type CreateRoleParams = { team: string; role_name: string; capabilities: string }

const createRoleCall = useCall<{ role: string }, CreateRoleParams>({
  url: method(API.createCustomRole),
  method: 'POST',
  immediate: false,
})

const deleteRoleCall = useCall<{ deleted: boolean }, { role: string }>({
  url: method(API.deleteCustomRole),
  method: 'POST',
  immediate: false,
})

let capabilitiesRequested = false

export function useTeamRoles() {
  ensureCapabilitiesLoaded()

  /** A role name -> the capability strings it grants, for quick lookup. */
  const capsByRole = computed<Record<string, string[]>>(() =>
    Object.fromEntries((rolesCall.data ?? []).map((r) => [r.name, r.capabilities])),
  )

  /** Role doc name -> its human label (custom roles autoname to TEAM-ROLE-#####). */
  function roleLabel(roleName: string): string {
    return (rolesCall.data ?? []).find((r) => r.name === roleName)?.role_name ?? roleName
  }

  async function createRole(roleName: string, capabilities: string[]): Promise<void> {
    try {
      await submitOrThrow(createRoleCall, {
        team: teamParams().team,
        role_name: roleName,
        capabilities: JSON.stringify(capabilities),
      })
      successToast(`Created role “${roleName}”.`)
      rolesCall.reload()
    } catch (e) {
      errorToast(e)
      throw e
    }
  }

  async function deleteRole(role: string, roleName: string): Promise<void> {
    try {
      await submitOrThrow(deleteRoleCall, { role })
      successToast(`Deleted role “${roleName}”.`)
      rolesCall.reload()
    } catch (e) {
      errorToast(e)
      throw e
    }
  }

  // System roles first, then by breadth of access (capability count, descending),
  // then name — so role columns/lists read as a hierarchy (Owner → … → Viewer)
  // rather than alphabetically.
  const roles = computed<TeamRoleRow[]>(() =>
    [...(rolesCall.data ?? [])].sort(
      (a, b) =>
        Number(b.is_system) - Number(a.is_system) ||
        b.capabilities.length - a.capabilities.length ||
        a.role_name.localeCompare(b.role_name),
    ),
  )

  return {
    roles,
    capabilities: computed<CapabilityInfo[]>(() => capabilitiesCall.data ?? []),
    capsByRole,
    roleLabel,
    loading: computed(() => rolesCall.loading || !rolesCall.isFinished),
    error: computed(() =>
      rolesCall.error ? getErrorMessage(rolesCall.error, "Couldn't load roles.") : null,
    ),
    creating: computed(() => createRoleCall.loading),
    reload: () => rolesCall.reload(),
    createRole,
    deleteRole,
  }
}

function ensureCapabilitiesLoaded(): void {
  if (capabilitiesRequested || capabilitiesCall.data || capabilitiesCall.loading) return
  capabilitiesRequested = true
  capabilitiesCall.reload().finally(() => {
    if (capabilitiesCall.error) capabilitiesRequested = false
  })
}
