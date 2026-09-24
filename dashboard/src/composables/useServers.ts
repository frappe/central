import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import signingInHtml from '@/assets/signing-in.html?raw'
import { useBusyRunner } from '@/composables/useBusyRunner'
import { useSession } from '@/composables/useSession'
import type { ServerAccess } from '@/lib/capabilities'
import { reportError } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type { RefreshResponse } from '@/types/api'
import type { VirtualMachine } from '@/types/Infrastructure/VirtualMachine'

type BenchLinkResponse = { url: string }
type SiteLinkResponse = { url: string | null; login_url: string | null }
type TeamParams = { team: string }
type CommandParams = {
	team: string
	resource_id: string
	take_snapshot?: number
}

export type ServerCommand = 'start' | 'stop' | 'restart' | 'terminate'

export type VirtualMachineRow = Pick<
	VirtualMachine,
	| 'name'
	| 'resource_id'
	| 'title'
	| 'region'
	| 'status'
	| 'plan'
	| 'frappe_version'
	| 'vcpus'
	| 'memory_megabytes'
	| 'disk_gigabytes'
	| 'ipv6_address'
	| 'public_ipv4'
	| 'gateway_url'
	| 'state_observed_at'
> &
	ServerAccess & {
		pending_action?: string | null
	}

const { activeTeam } = useSession()
const { busy, run, runOrThrow } = useBusyRunner()
const opening = ref('')

const refreshCall = useCall<RefreshResponse, TeamParams>({
	url: method(API.refreshServers),
	method: 'POST',
	immediate: false,
})

const startCall = commandCall(API.startServer)
const stopCall = commandCall(API.stopServer)
const restartCall = commandCall(API.restartServer)
const terminateCall = commandCall(API.terminateServer)
const commandCalls = {
	start: startCall,
	stop: stopCall,
	restart: restartCall,
	terminate: terminateCall,
}

const benchLinkCall = useCall<BenchLinkResponse, { server: string }>({
	url: method(API.getBenchLink),
	immediate: false,
})
const siteLinkCall = useCall<SiteLinkResponse, { name: string }>({
	url: method(API.loginSite),
	method: 'POST',
	immediate: false,
})

function commandCall(url: string) {
	return useCall<unknown, CommandParams>({
		url: method(url),
		method: 'POST',
		immediate: false,
	})
}

function commandLabel(command: ServerCommand): string {
	return `${command[0].toUpperCase()}${command.slice(1)}`
}

interface CommandOptions {
	takeSnapshot?: boolean
	throwOnError?: boolean
}

async function runCommand(
	command: ServerCommand,
	server: VirtualMachineRow,
	options: CommandOptions = {},
): Promise<boolean> {
	const team = activeTeam.value
	if (!team) return false

	const submit = () =>
		submitOrThrow(commandCalls[command], {
			team,
			resource_id: server.resource_id,
			...(command === 'terminate'
				? { take_snapshot: options.takeSnapshot ? 1 : 0 }
				: {}),
		})
	const message = `${commandLabel(command)} requested for ${server.title || server.resource_id}`

	if (options.throwOnError) {
		await runOrThrow(submit, null, server.resource_id)
		return true
	}
	return run(submit, message, server.resource_id)
}

async function refreshServers(): Promise<boolean> {
	const team = activeTeam.value
	if (!team) return false
	try {
		await submitOrThrow(refreshCall, { team })
		return true
	} catch (error) {
		reportError(error, { title: "Couldn't refresh servers" })
		return false
	}
}

function openLoadingTab(): { tab: Window | null; loadingUrl: string } {
	const loadingUrl = URL.createObjectURL(
		new Blob([signingInHtml], { type: 'text/html' }),
	)
	return { tab: window.open(loadingUrl, '_blank'), loadingUrl }
}

async function openBench(server: VirtualMachineRow): Promise<void> {
	if (opening.value) return
	opening.value = server.resource_id
	const { tab, loadingUrl } = openLoadingTab()
	try {
		await submitOrThrow(benchLinkCall, { server: server.resource_id })
		openResolvedUrl(benchLinkCall.data?.url, tab, 'server')
	} catch (error) {
		tab?.close()
		reportError(error, {
			title: `Couldn't open ${server.title || server.resource_id}`,
		})
	} finally {
		URL.revokeObjectURL(loadingUrl)
		opening.value = ''
	}
}

async function openSite(name: string): Promise<void> {
	if (opening.value) return
	opening.value = name
	const { tab, loadingUrl } = openLoadingTab()
	try {
		await submitOrThrow(siteLinkCall, { name })
		const url = siteLinkCall.data?.login_url || siteLinkCall.data?.url
		openResolvedUrl(url, tab, 'site')
	} catch (error) {
		tab?.close()
		reportError(error, { title: "Couldn't open this site" })
	} finally {
		URL.revokeObjectURL(loadingUrl)
		opening.value = ''
	}
}

function openResolvedUrl(
	url: string | null | undefined,
	tab: Window | null,
	target: 'server' | 'site',
) {
	if (url && tab) {
		tab.location.href = url
		return
	}
	if (url) {
		window.location.href = url
		return
	}

	tab?.close()
	reportError(undefined, {
		title: `Couldn't open this ${target}`,
		fallback: 'It may not be ready yet. Try again in a moment.',
	})
}

export function useServers() {
	return {
		refreshing: computed(() => refreshCall.loading),
		stale: computed<string[]>(() => refreshCall.data?.stale ?? []),
		busy,
		opening,
		refreshServers,
		runCommand,
		open: openBench,
		openBench,
		openSite,
	}
}
