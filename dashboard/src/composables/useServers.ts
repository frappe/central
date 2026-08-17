import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { errorToast, successToast } from '@/lib/toast'
import type { RefreshResponse } from '@/types/api'
import type { Asset } from '@/types/Central/Asset'

type BenchLinkResponse = {
	url: string
}

export type AssetRow = Pick<
	Asset,
	| 'name'
	| 'resource_id'
	| 'title'
	| 'cluster'
	| 'status'
	| 'plan'
	| 'frappe_version'
	| 'vcpus'
	| 'memory_megabytes'
	| 'disk_gigabytes'
	| 'ipv6_address'
	| 'public_ipv4'
	| 'gateway_url'
	| 'resize_in_progress'
	| 'last_synced_at'
> & {
	// Transitional label ("Terminating"/"Provisioning"/…) while an action is in flight.
	// Overlaid by central.api.servers.registry from the active Resource Action, not an
	// Asset field — so the row reads as "…ing" until the mirror catches up.
	pending_action?: string | null
}

// The server lifecycle command path (create / power / terminate / open-in-bench /
// mirror refresh). The fleet *list* is read separately through useServerMapData;
// callers reload that after a command, since a command's effect lands on the next
// mirror refresh (Atlas event push + reconcile pull), not synchronously.

const { activeTeam } = useSession()

// Param shapes for the lifecycle/SSO methods (central/api/servers.py, central/sso.py).
type TeamParams = { team: string }
type CommandParams = { team: string; resource_id: string }

// Re-pulls the mirror from every Active Atlas.
const refresh = useCall<RefreshResponse, TeamParams>({
	url: method(API.refreshAssets),
	method: 'POST',
	immediate: false,
})

type CreateParams = {
	team: string
	region: string
	title: string
	subdomain: string
	plan: string
	vcpus: number
	memory_megabytes: number
	disk_gigabytes: number
	cpu_max_cores?: number
	frappe_version?: string
}
const createCall = useCall<{ resource_id: string }, CreateParams>({
	url: method(API.createServer),
	method: 'POST',
	immediate: false,
})

// Design-your-own (composed) provision: the server is built from a composition
// (qty per resource) + its optimisation profile, billed à la carte (#80/#84).
type ComposedInclude = { resource_type: string; quantity: number; unit: string }
type CreateComposedParams = {
	team: string
	region: string
	title: string
	subdomain: string
	includes: ComposedInclude[]
	sub_category: string
	frappe_version?: string
}
const createComposedCall = useCall<
	{ resource_id: string },
	CreateComposedParams
>({
	url: method(API.createComposedServer),
	method: 'POST',
	immediate: false,
})

const startCall = useCall<unknown, CommandParams>({
	url: method(API.startServer),
	method: 'POST',
	immediate: false,
})
const stopCall = useCall<unknown, CommandParams>({
	url: method(API.stopServer),
	method: 'POST',
	immediate: false,
})
const terminateCall = useCall<unknown, CommandParams>({
	url: method(API.terminateServer),
	method: 'POST',
	immediate: false,
})
const benchLink = useCall<BenchLinkResponse, { asset: string }>({
	url: method(API.getBenchLink),
	immediate: false,
})

// One row mutates at a time; `busy` holds its resource_id so the row can show a
// spinner and gate its own menu. `opening` does the same for open-in-bench.
const busy = ref<string>('')
const opening = ref<string>('')

type Verb = 'Start' | 'Stop' | 'Terminate'

async function runCommand(
	call: typeof startCall,
	server: AssetRow,
	verb: Verb,
): Promise<void> {
	busy.value = server.resource_id
	try {
		// useCall surfaces HTTP failures on `.error` rather than throwing.
		await call.submit({
			team: activeTeam.value!,
			resource_id: server.resource_id,
		})
		if (call.error) throw call.error
		successToast(`${verb} requested for ${server.title || server.resource_id}`)
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

export function useServers() {
	async function refreshAssets(): Promise<void> {
		try {
			await refresh.submit({ team: activeTeam.value! })
			if (refresh.error) throw refresh.error
		} catch (e) {
			errorToast(e)
		}
	}

	function start(server: AssetRow) {
		return runCommand(startCall, server, 'Start')
	}
	function stop(server: AssetRow) {
		return runCommand(stopCall, server, 'Stop')
	}
	function terminate(server: AssetRow) {
		return runCommand(terminateCall, server, 'Terminate')
	}

	// Open the VM's bench via a scoped SSO assertion. The tab is opened
	// synchronously inside the click so it isn't popup-blocked, then pointed at the
	// minted URL once it resolves.
	async function open(server: AssetRow): Promise<void> {
		opening.value = server.resource_id
		const tab = window.open('', '_blank')
		try {
			await benchLink.submit({ asset: server.resource_id })
			if (benchLink.error) throw benchLink.error
			const url = benchLink.data?.url
			if (url && tab) tab.location.href = url
			else if (url) window.location.href = url
			else tab?.close()
		} catch (e) {
			tab?.close()
			errorToast(e)
		} finally {
			opening.value = ''
		}
	}

	// Provision a new server in a region. Returns the new resource_id on success
	// (so the caller can navigate), throws on failure (so it can surface the error).
	async function create(params: Omit<CreateParams, 'team'>): Promise<string> {
		await createCall.submit({ team: activeTeam.value!, ...params })
		// useCall surfaces HTTP failures on `.error` rather than throwing — surface
		// it and re-throw so the page keeps the user on the form.
		if (createCall.error) {
			errorToast(createCall.error)
			throw createCall.error
		}
		successToast(`Creating ${params.title} in ${params.region}`)
		return createCall.data?.resource_id ?? ''
	}

	// Provision a design-your-own (composed) server. Same contract as create().
	async function createComposed(
		params: Omit<CreateComposedParams, 'team'>,
	): Promise<string> {
		await createComposedCall.submit({ team: activeTeam.value!, ...params })
		if (createComposedCall.error) {
			errorToast(createComposedCall.error)
			throw createComposedCall.error
		}
		successToast(`Creating ${params.title} in ${params.region}`)
		return createComposedCall.data?.resource_id ?? ''
	}

	return {
		refreshing: computed(() => refresh.loading),
		creating: computed(() => createCall.loading),
		creatingComposed: computed(() => createComposedCall.loading),
		// Atlas instances that couldn't be reached on the last refresh — their rows
		// show last-known data.
		stale: computed<string[]>(() => refresh.data?.stale ?? []),
		busy,
		opening,
		refreshAssets,
		create,
		createComposed,
		start,
		stop,
		terminate,
		open,
	}
}
