import type { DropdownOption, DropdownOptions } from 'frappe-ui'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSupport } from '@/composables/useSupport'
import { ACCESS_LOCKED_REASON, type ServerActions } from '@/lib/capabilities'
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
	| 'ssh-console'
	| 'tty-console'
	| 'rename'
	| 'terminate'

export interface ServerMenuOptions {
	/** The address of the site this machine carries. Open goes to that site, not the bench. */
	site?: string | null
	/** The caller shows Overview and Open itself, and its Settings tab offers Resize
	 *  and Terminate, as on the server page. */
	isOnServerPage?: boolean
}

type Run = (verb: ServerMenuVerb) => void

/** One server's actions in groups, from most to least frequent so Terminate sits
 *  last and apart. Status and capability gate each item the way the API does, so the
 *  menu never offers a call that would fail. Empty groups are left out. */
export function getServerMenuGroups(
	server: VirtualMachineRow,
	allowed: ServerActions,
	run: Run,
	options: ServerMenuOptions = {},
): DropdownOption[][] {
	const entry = (
		verb: ServerMenuVerb,
		label: string,
		icon: string,
		description?: string,
	) => ({
		label,
		icon,
		description,
		onClick: () => run(verb),
	})

	// A server mid-action or still setting up offers only reads.
	const isChangeable = canChange(server)
	const isBusy = !!server.pending_action

	const groups: DropdownOption[][] = [
		getViewItems(server, allowed, entry, options),
		isBusy ? [] : getPowerItems(server, allowed, entry),
		isChangeable ? getChangeItems(allowed, entry, options) : [],
		[
			// Renaming is rare, so it lives on the server page only.
			...(options.isOnServerPage && allowed.resize
				? [entry('rename', 'Rename', 'lucide-pencil')]
				: []),
			{
				label: 'Copy server ID',
				icon: 'lucide-copy',
				onClick: () => copyServerId(server),
			},
			...getSupportItems(server, options.site),
		],
		isChangeable && allowed.terminate && !options.isOnServerPage
			? [{ ...entry('terminate', 'Terminate', 'lucide-trash-2'), theme: 'red' }]
			: [],
	]

	return groups.filter((items) => items.length)
}

/** The same actions as a frappe-ui Dropdown, one unlabelled section per group. */
export function getServerMenu(
	server: VirtualMachineRow,
	allowed: ServerActions,
	run: Run,
	options: ServerMenuOptions = {},
): DropdownOptions {
	return getServerMenuGroups(server, allowed, run, options).map(
		(items, index) => ({ group: `${index}`, hideLabel: true, options: items }),
	)
}

/** A submenu's items as flat options named "Parent: Child", for a list that cannot nest. */
export function withSubmenuItems(option: DropdownOption): DropdownOption[] {
	if (!option.submenu) return [option]

	return option.submenu
		.filter((item): item is DropdownOption => !('group' in item))
		.map((item) => ({
			...item,
			label: `${option.label}: ${item.label}`,
			disabled: option.disabled || item.disabled,
		}))
}

type Entry = (
	verb: ServerMenuVerb,
	label: string,
	icon: string,
	description?: string,
) => DropdownOption

function getViewItems(
	server: VirtualMachineRow,
	allowed: ServerActions,
	entry: Entry,
	{ site, isOnServerPage }: ServerMenuOptions,
): DropdownOption[] {
	const opensSite = !!site
	const isRunning = server.status === 'Running'
	const isBusy = !!server.pending_action
	const canOpen = allowed.open && !isBusy && !isSettingUp(server.status)
	const items: DropdownOption[] = []

	if (!isOnServerPage) items.push(entry('overview', 'Overview', 'lucide-gauge'))

	// Without a site, Open signs in to Pilot, which a free trial locks.
	if (canOpen && !isOnServerPage)
		items.push(
			...lockable(allowed, !opensSite, {
				...entry(
					'open',
					opensSite ? 'Visit site' : 'Open server',
					opensSite ? 'lucide-globe' : 'lucide-server',
				),
				disabled: !isRunning || !(opensSite || server.gateway_url),
			}),
		)

	// On a site server the primary open visits the site, so the bench gets its own entry.
	if (canOpen && opensSite)
		items.push(
			...lockable(allowed, true, {
				...entry('pilot', 'Open server', 'lucide-server'),
				disabled: !isRunning || !server.gateway_url,
			}),
		)

	if (allowed.console && !isBusy)
		items.push(
			...lockable(allowed, true, {
				label: 'Web console',
				icon: 'lucide-square-terminal',
				disabled: !isRunning,
				submenu: [
					entry(
						'ssh-console',
						'SSH session',
						'lucide-terminal',
						'Shell as root. No password needed.',
					),
					entry(
						'tty-console',
						'Serial console (TTY)',
						'lucide-monitor-cog',
						'Boot output and login prompt. Needs a user password.',
					),
				],
			}),
		)

	return items
}

/** An action a free trial locks stays in the menu, off, with the reason. */
function lockable(
	allowed: ServerActions,
	isServerAccess: boolean,
	option: DropdownOption,
): DropdownOption[] {
	if (!isServerAccess || !allowed.isAccessLocked) return [option]

	// A locked row has nothing to open, so it drops its submenu and the chevron with it.
	const { submenu: _submenu, ...row } = option as DropdownOption & {
		submenu?: unknown
	}

	// Every menu row takes a description, but the option union does not say so.
	return [
		{
			...row,
			disabled: true,
			description: ACCESS_LOCKED_REASON,
		} as DropdownOption,
	]
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
	{ isOnServerPage }: ServerMenuOptions,
): DropdownOption[] {
	const items: DropdownOption[] = []

	if (allowed.resize && !isOnServerPage)
		items.push(entry('resize', 'Resize', 'lucide-sliders-horizontal'))

	if (allowed.snapshot)
		items.push(
			...lockable(
				allowed,
				true,
				entry('snapshot', 'Take snapshot', 'lucide-camera'),
			),
		)

	return items
}

function getSupportItems(
	server: VirtualMachineRow,
	site: string | null | undefined,
): DropdownOption[] {
	const reference = server.title
		? `${server.title} (${server.resource_id})`
		: server.resource_id
	const option = useSupport().getContactSupportOption({
		Server: reference,
		Site: site,
	})
	return option ? [option] : []
}

// One line support can paste into a ticket to find the VM in Central and in Atlas.
async function copyServerId(server: VirtualMachineRow): Promise<void> {
	const reference = [server.resource_id, server.atlas_vm_id, server.region]
		.filter(Boolean)
		.join(' · ')

	if (await copyToClipboard(reference)) successToast('Server ID copied')
	else reportError('Could not copy the server ID.')
}
