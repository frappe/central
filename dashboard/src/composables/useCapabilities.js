// Mirrors Central's capability IAM (fixtures: Capability + Team Role). Computed
// ONCE here and bound to every screen: reads gate on a *:view capability,
// mutations on the matching manage capability. The server re-checks every call —
// the UI just avoids offering buttons the API will 403.
//
// Real capabilities (central/fixtures/capability.json):
//   billing:view, billing:manage,
//   team:edit, team:manage_members, team:delete,
//   cluster:view,
//   server:view/open/create/power/resize/snapshot/terminate
// There is NO team:view / atlas:* — team visibility is "being a member" (any cap
// on the team), and the compute (server) screens map to the server:* family.
// server:view lists servers; server:open is the distinct console-open gate.

import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'

const { currentTeam } = useTeam()

// Re-fetches whenever the active team changes.
const caps = useCall({
  url: m(API.myCapabilities),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

function has(cap) {
  return caps.data?.includes(cap) ?? false
}

export function useCapabilities() {
  return {
    caps,
    has,
    loading: computed(() => caps.loading),
    // Membership: any capability on the active team means the user belongs to it.
    isMember: computed(() => (caps.data?.length ?? 0) > 0),
    // Billing
    canView: computed(() => has('billing:view')),
    canManage: computed(() => has('billing:manage')),
    // Team & identity — anyone on the team sees the roster; member management
    // is the manage gate.
    canViewTeam: computed(() => (caps.data?.length ?? 0) > 0),
    canManageTeam: computed(() => has('team:manage_members')),
    // Compute (servers) — viewing resources vs acting on them.
    canViewAtlas: computed(() => has('server:view')),
    canManageAtlas: computed(() => has('server:create') || has('server:power')),
  }
}
