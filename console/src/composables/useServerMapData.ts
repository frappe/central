import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { useFrappeListInvalidation } from '@/composables/common/useFrappeRealtime'
import { getErrorMessage } from '@/lib/toast'
import type { AssetRow } from '@/composables/useServers'

// The team's whole fleet in one read — the map clusters and filters client-side,
// so unlike the reportview-backed useServers list there is no pagination. Reads
// go through central.api.servers.registry (server:view gated, unpaginated by
// design); the Asset mirror itself is kept fresh by Atlas's event push + the
// reconcile pull.

type RegistryResponse = { team: string; assets: AssetRow[] }

const registry = useCall<RegistryResponse, { team: string }>({
  url: method(API.registry),
  params: teamParams,
  refetch: true,
  immediate: false,
})

whenTeamReady(() => registry.reload())

// The socket is only reachable from component scope, so each consumer registers
// its own (self-disposing) listener — this shared timer coalesces them so
// simultaneous consumers still cause exactly one reload per event burst.
let reloadTimer: number | undefined
function reloadOnce(): void {
  window.clearTimeout(reloadTimer)
  reloadTimer = window.setTimeout(() => registry.reload(), 150)
}

export function useServerMapData() {
  // db_set(..., notify=True) writes (resize flag, termination) land live.
  useFrappeListInvalidation('Asset', reloadOnce, { debounceMs: 0 })

  return {
    // Terminated servers are gone, not a state to render — excluded here so no
    // consumer has to remember to.
    assets: computed<AssetRow[]>(() =>
      (registry.data?.assets ?? []).filter((asset) => asset.status !== 'Terminated'),
    ),
    loading: computed(() => registry.loading),
    error: computed(() =>
      registry.error ? getErrorMessage(registry.error, "Couldn't load servers.") : null,
    ),
    reload: () => registry.reload(),
  }
}
