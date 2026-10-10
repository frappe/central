import type { DropdownOption, DropdownOptions } from 'frappe-ui'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ServerActions } from '@/lib/capabilities'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError, successToast } from '@/lib/feedback'
import { canChange, canStart, canStop, isSettingUp } from '@/lib/status'

export type ServerMenuVerb =
	| 'overview'
	| 'open'
	| 'pilot'
	| 'start'
	| 'stop'
	| 'restart'
	| 'resize'
	| 'snapshot'
	| 'console'
	| 'terminate'

export interface ServerMenuOptions {
	/** This machine carries a site. Open goes to that site, not the bench. */
	opensSite?: boolean
	/** The caller shows Overview and Open itself, as on the server page. */
	isOnServerPage?: boolean
}

type Run = (verb: ServerMenuVerb) => void

/** One server's action menu, grouped from most to least frequent so Terminate sits
 *  last and apart. Status and capability gate each item the way the API does, so the
 *  menu never offers a call that would fail. */
export function getServerMenu(
	server: VirtualMachineRow,
	allowed: ServerActions,
	run: Run,
	options: ServerMenuOptions = {},
): DropdownOptions {
	const entry = (verb: ServerMenuVerb, label: string, icon: string) => ({
		label,
		icon,
		onClick: () => run(verb),
	})

	// A server mid-action or still setting up offers only reads.
	const isChangeable = canChange(server)
	const isBusy = !!server.pending_action

	const groups: DropdownOption[][] = [
		getViewItems(server, allowed, entry, options),
		isBusy ? [] : getPowerItems(server, allowed, entry),
		isChangeable ? getChangeItems(allowed, entry) : [],
		[
			{
				label: 'Copy server ID',
				icon: 'lucide-copy',
				onClick: () => copyServerId(server),
			},
		],
		isChangeable && allowed.terminate
			? [{ ...entry('terminate', 'Terminate', 'lucide-trash-2'), theme: 'red' }]
			: [],
	]

	return groups
		.filter((items) => items.length)
		.map((items, index) => ({
			group: `${index}`,
			hideLabel: true,
			options: items,
		}))
}

type Entry = (
	verb: ServerMenuVerb,
	label: string,
	icon: string,
) => DropdownOption

function getViewItems(
	server: VirtualMachineRow,
	allowed: ServerActions,
	entry: Entry,
	{ opensSite, isOnServerPage }: ServerMenuOptions,
): DropdownOption[] {
	const isRunning = server.status === 'Running'
	const isBusy = !!server.pending_action
	const canOpen = allowed.open && !isBusy && !isSettingUp(server.status)
	const items: DropdownOption[] = []

	if (!isOnServerPage) items.push(entry('overview', 'Overview', 'lucide-gauge'))

	if (canOpen && !isOnServerPage)
		items.push({
			...entry(
				'open',
				opensSite ? 'Visit site' : 'Open server',
				opensSite ? 'lucide-globe' : 'lucide-server',
			),
			disabled: !isRunning || !(opensSite || server.gateway_url),
		})

	// On a site server the primary open visits the site, so the bench gets its own entry.
	if (canOpen && opensSite)
		items.push({
			...entry('pilot', 'Open server', 'lucide-server'),
			disabled: !isRunning || !server.gateway_url,
		})

	if (allowed.console && !isBusy)
		items.push({
			...entry('console', 'Web console', 'lucide-terminal'),
			disabled: !isRunning,
		})

	return items
}

function getPowerItems(
	server: VirtualMachineRow,
	allowed: ServerActions,
	entry: Entry,
): DropdownOption[] {
	if (!allowed.power) return []

	if (canStart(server.status)) return [entry('start', 'Start', 'lucide-play')]

	// Only a running server can stop or restart; the API refuses both otherwise.
	if (!canStop(server.status)) return []

	return [
		entry('stop', 'Stop', 'lucide-square'),
		entry('restart', 'Restart', 'lucide-rotate-ccw'),
	]
}

function getChangeItems(
	allowed: ServerActions,
	entry: Entry,
): DropdownOption[] {
	const items: DropdownOption[] = []

	if (allowed.resize)
		items.push(entry('resize', 'Resize', 'lucide-sliders-horizontal'))

	if (allowed.snapshot)
		items.push(entry('snapshot', 'Take snapshot', 'lucide-camera'))

	return items
}

// One line support can paste into a ticket to find the VM in Central and in Atlas.
async function copyServerId(server: VirtualMachineRow): Promise<void> {
	const reference = [server.resource_id, server.atlas_vm_id, server.region]
		.filter(Boolean)
		.join(' · ')

	if (await copyToClipboard(reference)) successToast('Server ID copied')
	else reportError('Could not copy the server ID.')
}
