// Mirrors Central's capability IAM. Computed ONCE here and bound to every screen:
// reads gate on `*:view`, mutations on `*:manage`. The server re-checks every
// call — the UI just avoids offering buttons the API will 403.

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
    // Billing
    canView: computed(() => has('billing:view')),
    canManage: computed(() => has('billing:manage')),
    // Team & identity
    canViewTeam: computed(() => has('team:view')),
    canManageTeam: computed(() => has('team:manage')),
    // Atlas
    canViewAtlas: computed(() => has('atlas:view')),
    canManageAtlas: computed(() => has('atlas:manage')),
  }
}
