import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'

// Mirrors Central's capability IAM (central/iam.my_capabilities). Computed once
// and bound to every screen: the UI just avoids offering buttons the API would
// 403 — the server re-checks every call. Re-fetches whenever the active team
// changes. The lifecycle gates map one-to-one to the server-side checks in
// central/api/servers.py: power drives start/stop, terminate destroys, open mints the
// bench SSO link.

const capsCall = useCall<string[], { team: string }>({
  url: method(API.myCapabilities),
  params: teamParams,
  refetch: true,
  immediate: false,
})

whenTeamReady(() => capsCall.reload())

function has(cap: string): boolean {
  return capsCall.data?.includes(cap) ?? false
}

export function useCapabilities() {
  return {
    loading: computed(() => capsCall.loading),
    canViewServers: computed(() => has('server:view')),
    canCreateServer: computed(() => has('server:create')),
    canPowerServer: computed(() => has('server:power')),
    canTerminateServer: computed(() => has('server:terminate')),
    canOpenServer: computed(() => has('server:open')),
    canViewClusters: computed(() => has('cluster:view')),
    canViewBilling: computed(() => has('billing:view')),
    canManageBilling: computed(() => has('billing:manage')),
    reload: () => capsCall.reload(),
  }
}
