import { useCall } from 'frappe-ui'
import { computed, onScopeDispose } from 'vue'
import { API, method } from '@/api/methods'
import { useFrappeDocEventListener } from '@/composables/useFrappeRealtime'
import type { AssetRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage, isAbortError } from '@/lib/toast'

// The team's whole fleet in one read — its servers and its self-serve sites (each a
// 1:1-backed VM), so the map/panel unify them from a single call. The map clusters and
// filters client-side, so unlike the reportview-backed useServers list there is no
// pagination. Reads go through central.api.servers.registry (server:view gated,
// unpaginated by design), and a region's state reports keep it fresh.

// A site is a VM peer of an asset: `name` is the FQDN (stable id + terminate key),
// `subdomain` the user-entered display name (e.g. "demo.in").
export interface SiteRow {
	name: string
	subdomain: string | null
	status: string
	region: string | null
	url: string | null
	// Transitional label while a site action is in flight (see AssetRow.pending_action).
	pending_action?: string | null
}

type RegistryResponse = { team: string; assets: AssetRow[]; sites: SiteRow[] }

const { activeTeam } = useSession()

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
	// Central publishes into the active team's room whenever one of its servers moves,
	// so a state report, a power action or a resize lands here without polling. The
	// payload is identity only: this feed stays the single source of truth, and the
	// shared debounce coalesces a burst of events into one reload.
	useFrappeDocEventListener(
		'Team',
		activeTeam,
		'server_state_changed',
		reloadOnce,
	)
	// The invalidation listener self-disposes per scope; clear the shared debounce
	// too so a pending reload never fires into a torn-down singleton.
	onScopeDispose(() => window.clearTimeout(reloadTimer))

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
