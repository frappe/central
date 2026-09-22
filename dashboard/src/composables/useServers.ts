import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { errorToast, successToast } from '@/lib/toast'
import type { RefreshResponse } from '@/types/api'
import type { VirtualMachine } from '@/types/Central/VirtualMachine'

type BenchLinkResponse = {
	url: string
}

export type VirtualMachineRow = Pick<
	VirtualMachine,
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
	| 'state_observed_at'
> & {
	// Transitional label ("Terminating"/"Provisioning"/…) while an action is in flight.
	// Overlaid by central.api.servers.registry from the active Resource Action, not an
	// VirtualMachine field — so the row reads as "…ing" until the mirror catches up.
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
	url: method(API.refreshServers),
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
const restartCall = useCall<unknown, CommandParams>({
	url: method(API.restartServer),
	method: 'POST',
	immediate: false,
})
const terminateCall = useCall<unknown, CommandParams>({
	url: method(API.terminateServer),
	method: 'POST',
	immediate: false,
})
const benchLink = useCall<BenchLinkResponse, { server: string }>({
	url: method(API.getBenchLink),
	immediate: false,
})

// One row mutates at a time; `busy` holds its resource_id so the row can show a
// spinner and gate its own menu. `opening` does the same for open-in-bench.
const busy = ref<string>('')
const opening = ref<string>('')

type Verb = 'Start' | 'Stop' | 'Restart' | 'Terminate'

async function runCommand(
	call: typeof startCall,
	server: VirtualMachineRow,
	verb: Verb,
	// A quick, reversible power action toasts on failure; a destructive one (terminate)
	// throws so the caller can hold its confirm dialog open and show the reason inline.
	surface: 'toast' | 'throw' = 'toast',
): Promise<void> {
	busy.value = server.resource_id
	try {
		// useCall surfaces HTTP failures on `.error` rather than throwing.
		await call.submit({
			team: activeTeam.value!,
			resource_id: server.resource_id,
		})
		if (call.error) throw call.error
		if (surface === 'toast')
			successToast(
				`${verb} requested for ${server.title || server.resource_id}`,
			)
	} catch (e) {
		if (surface === 'throw') throw e
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

export function useServers() {
	async function refreshServers(): Promise<void> {
		try {
			await refresh.submit({ team: activeTeam.value! })
			if (refresh.error) throw refresh.error
		} catch (e) {
			errorToast(e)
		}
	}

	function start(server: VirtualMachineRow) {
		return runCommand(startCall, server, 'Start')
	}
	function stop(server: VirtualMachineRow) {
		return runCommand(stopCall, server, 'Stop')
	}
	function restart(server: VirtualMachineRow) {
		return runCommand(restartCall, server, 'Restart')
	}
	function terminate(server: VirtualMachineRow) {
		return runCommand(terminateCall, server, 'Terminate', 'throw')
	}

	// Open the VM's bench via a scoped SSO assertion. The tab is opened
	// synchronously inside the click so it isn't popup-blocked, then pointed at the
	// minted URL once it resolves.
	async function open(server: VirtualMachineRow): Promise<void> {
		opening.value = server.resource_id
		const tab = window.open('', '_blank')
		try {
			await benchLink.submit({ server: server.resource_id })
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

	return {
		refreshing: computed(() => refresh.loading),
		// Atlas instances that couldn't be reached on the last refresh — their rows
		// show last-known data.
		stale: computed<string[]>(() => refresh.data?.stale ?? []),
		busy,
		opening,
		refreshServers,
		start,
		stop,
		restart,
		terminate,
		open,
	}
}
