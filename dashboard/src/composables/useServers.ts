import { useCall, useColorScheme } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useBusyRunner } from '@/composables/useBusyRunner'
import { useSession } from '@/composables/useSession'
import { frappeErrorType } from '@/lib/auth'
import type { ServerAccess } from '@/lib/capabilities'
import { getErrorMessage, infoToast, reportError } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import { LoadingTab } from '@/lib/loadingTab'
import { __ } from '@/lib/translate'
import type { RefreshResponse } from '@/types/api'
import type { VirtualMachine } from '@/types/Infrastructure/VirtualMachine'

type BenchLinkResponse = { url: string }
type SiteLinkResponse = {
	url: string | null
	login_url: string | null
	login_pending: boolean
}
type TeamParams = { team: string }
type CommandParams = {
	team: string
	resource_id: string
	take_snapshot?: number
}

/** SSH opens a root shell. TTY opens the serial console, which asks for a password. */
export type ConsoleMode = 'ssh' | 'tty'
type ConsoleParams = CommandParams & { mode: ConsoleMode }

export type ServerCommand = 'start' | 'stop' | 'restart' | 'terminate'

export type VirtualMachineRow = Pick<
	VirtualMachine,
	| 'name'
	| 'resource_id'
	| 'atlas_vm_id'
	| 'title'
	| 'region'
	| 'status'
	| 'sleep_state'
	| 'plan'
	| 'frappe_version'
	| 'vcpus'
	| 'memory_megabytes'
	| 'disk_gigabytes'
	| 'ipv6_address'
	| 'public_ipv4'
	| 'public_ipv6'
	| 'image_offering'
	| 'gateway_url'
	| 'state_observed_at'
> &
	ServerAccess & {
		pending_action?: string | null
		plan_title?: string | null
		image_title?: string | null
		image_description?: string | null
		has_wireguard_access?: boolean
		creation?: string
		created_by?: string | null
		created_by_name?: string | null
		/** The server's Pilot audience, which a link from that Pilot names it by. */
		pilot_audience?: string | null
		/** Sleep when idle is internal-only until it lowers the customer's price. */
		is_idle_sleep_available?: boolean
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
const consoleCall = useCall<{ url: string }, ConsoleParams>({
	url: method(API.openConsole),
	method: 'POST',
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

/** Show the failure in the loading tab and in the dashboard, since the person may look at either. */
function reportOpenFailure(
	tab: LoadingTab | null,
	error: unknown,
	options: { title: string; fallback?: string },
): void {
	tab?.fail(options.title, getErrorMessage(error, options.fallback))
	reportError(error, options)
}

/** Pilot keeps its own theme, so the bench link carries this dashboard's choice to it. */
function withColorScheme(url: string | undefined): string | undefined {
	if (!url) return url

	const link = new URL(url, window.location.href)
	link.searchParams.set('theme', useColorScheme().colorScheme.value)
	return link.href
}

type LinkAttempt = { url?: string | null; isWaking: boolean }
type WaitingCopy = { hold: string; toast: string; timeout: string }

/** Ask `attempt` for a link every 3 seconds, for up to 5 minutes, while it says the server is
 *  waking. Pilot starts some time after a boot, and a sleeping server wakes on a request. */
async function retryWhileWaking(
	tab: LoadingTab | null,
	attempt: () => Promise<LinkAttempt>,
	copy: WaitingCopy,
): Promise<string | null | undefined> {
	const deadline = Date.now() + 5 * 60 * 1000
	let hasToldWaiting = false
	for (;;) {
		const { url, isWaking } = await attempt()
		if (!isWaking) return url
		if (Date.now() > deadline) throw new Error(copy.timeout)
		// The person closed the waiting tab, so they no longer want the link.
		if (tab?.isClosed) return undefined

		tab?.hold(copy.hold)
		// Without a waiting tab, the page itself must say why nothing opens yet.
		if (!tab && !hasToldWaiting) {
			infoToast(copy.toast)
			hasToldWaiting = true
		}
		await new Promise((resolve) => setTimeout(resolve, 3000))
	}
}

/** The bench's login link. Central refuses one while Pilot starts after a create, boot,
 *  resize, or wake. */
async function getBenchLink(
	server: VirtualMachineRow,
	tab: LoadingTab | null,
): Promise<string | undefined> {
	const url = await retryWhileWaking(
		tab,
		async () => {
			try {
				await submitOrThrow(benchLinkCall, { server: server.resource_id })
				return { url: benchLinkCall.data?.url, isWaking: false }
			} catch (error) {
				if (frappeErrorType(error) === 'PilotStarting')
					return { isWaking: true }
				throw error
			}
		},
		{
			hold: __('Holding short. Pilot is starting up.'),
			toast: __("Pilot is starting. It opens here when it's ready."),
			timeout: __("Pilot isn't answering yet. Try again in a minute."),
		},
	)
	return withColorScheme(url ?? undefined)
}

/** The site's login link. Central has none while the site does not answer, such as while
 *  its sleeping server wakes. */
async function getSiteLink(
	name: string,
	tab: LoadingTab | null,
): Promise<string | null | undefined> {
	return retryWhileWaking(
		tab,
		async () => {
			await submitOrThrow(siteLinkCall, { name })
			const site = siteLinkCall.data
			return {
				url: site?.login_url || site?.url,
				isWaking: !!site?.login_pending,
			}
		},
		{
			hold: __('Holding short. The server is waking up.'),
			toast: __("The server is waking up. The site opens when it's ready."),
			timeout: __("The site didn't wake up. Try again in a minute."),
		},
	)
}

/** `inPlace` replaces this page, for a link that opens the bench without a click. */
async function openBench(
	server: VirtualMachineRow,
	{ inPlace = false } = {},
): Promise<void> {
	if (opening.value) return
	opening.value = server.resource_id
	const name = server.title || server.resource_id
	const tab = inPlace ? null : LoadingTab.open(name)
	try {
		const url = await getBenchLink(server, tab)
		if (tab?.isClosed) return
		openResolvedUrl(url, tab, 'server')
	} catch (error) {
		reportOpenFailure(tab, error, { title: `Couldn't open ${name}` })
	} finally {
		tab?.dispose()
		opening.value = ''
	}
}

/** Open the server's Atlas web console in a popup. Atlas spends a token on first
 *  use, so every request mints a new one. One window per server: a second request
 *  replaces the session in that window. */
async function openConsole(
	server: VirtualMachineRow,
	mode: ConsoleMode,
): Promise<void> {
	const team = activeTeam.value
	if (!team || opening.value) return
	opening.value = server.resource_id
	const tab = LoadingTab.open(
		__('the console'),
		`console-${server.resource_id}`,
		'popup,width=960,height=640',
	)
	try {
		await submitOrThrow(consoleCall, {
			team,
			resource_id: server.resource_id,
			mode,
		})
		openResolvedUrl(consoleCall.data?.url, tab, 'console')
	} catch (error) {
		reportOpenFailure(tab, error, { title: "Couldn't open the console" })
	} finally {
		tab?.dispose()
		opening.value = ''
	}
}

async function openSite(name: string): Promise<void> {
	if (opening.value) return
	opening.value = name
	const tab = LoadingTab.open(name)
	try {
		const url = await getSiteLink(name, tab)
		if (tab?.isClosed) return
		openResolvedUrl(url, tab, 'site')
	} catch (error) {
		reportOpenFailure(tab, error, { title: "Couldn't open this site" })
	} finally {
		tab?.dispose()
		opening.value = ''
	}
}

function openResolvedUrl(
	url: string | null | undefined,
	tab: LoadingTab | null,
	target: 'server' | 'site' | 'console',
) {
	if (url && tab) {
		tab.takeoff(url)
		return
	}
	if (url) {
		window.location.href = url
		return
	}

	reportOpenFailure(tab, undefined, {
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
		openConsole,
		openSite,
	}
}
