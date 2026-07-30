import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { useFrappeListInvalidation } from '@/composables/common/useFrappeRealtime'
import { getErrorMessage, isAbortError } from '@/lib/toast'
import type { AssetRow } from '@/composables/useServers'

// The team's whole fleet in one read — servers (the Asset mirror) and self-serve
// sites (the Site mirror, each a 1:1-backed VM), so the map/panel unify them from a
// single call. The map clusters and filters client-side, so unlike the
// reportview-backed useServers list there is no pagination. Reads go through
// central.api.servers.registry (server:view gated, unpaginated by design); both
// mirrors are kept fresh by Atlas's event push + the reconcile pull.

// A site is a VM peer of an asset: `name` is the FQDN (stable id + terminate key),
// `subdomain` the user-entered display name (e.g. "demo.in").
export interface SiteRow {
	name: string
	subdomain: string | null
	status: string
	region: string | null
	url: string | null
}

type RegistryResponse = { team: string; assets: AssetRow[]; sites: SiteRow[] }

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
	// Either mirror changing reloads the one feed; db_set(..., notify=True) writes
	// (resize flag, termination) land live. One shared debounce coalesces a burst
	// that touches both doctypes into a single reload.
	useFrappeListInvalidation(['Asset', 'Site'], reloadOnce, { debounceMs: 0 })

	return {
		// Terminated servers are gone, not a state to render — excluded here so no
		// consumer has to remember to. (Sites exclude Terminated server-side.)
		assets: computed<AssetRow[]>(() =>
			(registry.data?.assets ?? []).filter(
				(asset) => asset.status !== 'Terminated',
			),
		),
		sites: computed<SiteRow[]>(() => registry.data?.sites ?? []),
		loading: computed(() => registry.loading),
		error: computed(() => {
			if (!registry.error || isAbortError(registry.error)) return null
			return getErrorMessage(registry.error, "Couldn't load servers.")
		}),
		reload: () => registry.reload(),
	}
}
