<script setup lang="ts">
import type { DropdownOption, DropdownOptions } from 'frappe-ui'
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import { getServerActions } from '@/lib/capabilities'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError, successToast } from '@/lib/feedback'
import { canStart, canStop, isSettingUp, isTerminated } from '@/lib/status'

// The lifecycle menu for one server row. Which actions show is gated by both the
// server's status and the user's capabilities on this server — the same rules the API
// enforces in central/api/servers.py, so we never offer a button that would 403. The
// component is presentational: it emits the chosen verb; the page owns the calls.
const props = defineProps<{
	server: VirtualMachineRow
	canOpen: boolean
	canPower: boolean
	canResize: boolean
	canTerminate: boolean
	canSnapshot?: boolean
	canOpenConsole?: boolean
	busy?: boolean
	opening?: boolean
	/** This machine carries a site. Open goes to that site, not the bench. */
	opensSite?: boolean
}>()

const emit = defineEmits<{
	overview: [server: VirtualMachineRow]
	open: [server: VirtualMachineRow]
	pilot: [server: VirtualMachineRow]
	start: [server: VirtualMachineRow]
	stop: [server: VirtualMachineRow]
	restart: [server: VirtualMachineRow]
	resize: [server: VirtualMachineRow]
	snapshot: [server: VirtualMachineRow]
	console: [server: VirtualMachineRow]
	terminate: [server: VirtualMachineRow]
}>()

const allowed = computed(() =>
	getServerActions(props.server, {
		open: props.canOpen,
		power: props.canPower,
		resize: props.canResize,
		snapshot: !!props.canSnapshot,
		terminate: props.canTerminate,
		console: !!props.canOpenConsole,
	}),
)

// One line support can paste into a ticket to find the VM in Central and in Atlas.
async function copyServerId(): Promise<void> {
	const { resource_id, atlas_vm_id, region } = props.server
	const reference = [resource_id, atlas_vm_id, region]
		.filter(Boolean)
		.join(' · ')
	if (await copyToClipboard(reference)) successToast('Server ID copied')
	else reportError('Could not copy the server ID.')
}

function getViewActions(isOnlyReading: boolean): DropdownOption[] {
	const items: DropdownOption[] = [
		{
			label: 'Overview',
			icon: 'lucide-gauge',
			onClick: () => emit('overview', props.server),
		},
	]
	const isRunning = props.server.status === 'Running'
	if (allowed.value.open && !isOnlyReading) {
		items.push({
			label: props.opensSite ? 'Visit site' : 'Open server',
			icon: props.opensSite ? 'lucide-globe' : 'lucide-server',
			disabled: !isRunning || !(props.opensSite || props.server.gateway_url),
			onClick: () => emit('open', props.server),
		})
		// On a site server the first entry visits the site, so the server gets its own.
		if (props.opensSite)
			items.push({
				label: 'Open server',
				icon: 'lucide-server',
				disabled: !isRunning || !props.server.gateway_url,
				onClick: () => emit('pilot', props.server),
			})
	}
	if (allowed.value.console && !props.server.pending_action)
		items.push({
			label: 'Web console',
			icon: 'lucide-terminal',
			disabled: !isRunning,
			onClick: () => emit('console', props.server),
		})
	return items
}

function getPowerActions(): DropdownOption[] {
	if (!allowed.value.power) return []
	if (canStart(props.server.status))
		return [
			{
				label: 'Start',
				icon: 'lucide-play',
				onClick: () => emit('start', props.server),
			},
		]
	// Only a running server can stop or restart; the API refuses both otherwise.
	if (!canStop(props.server.status)) return []
	return [
		{
			label: 'Stop',
			icon: 'lucide-square',
			onClick: () => emit('stop', props.server),
		},
		{
			label: 'Restart',
			icon: 'lucide-rotate-ccw',
			onClick: () => emit('restart', props.server),
		},
	]
}

function getChangeActions(): DropdownOption[] {
	const items: DropdownOption[] = []
	if (allowed.value.resize)
		items.push({
			label: 'Resize',
			icon: 'lucide-sliders-horizontal',
			onClick: () => emit('resize', props.server),
		})
	if (allowed.value.snapshot)
		items.push({
			label: 'Take snapshot',
			icon: 'lucide-camera',
			onClick: () => emit('snapshot', props.server),
		})
	return items
}

// Groups run from most to least frequent, so the destructive action sits last and apart.
const options = computed<DropdownOptions>(() => {
	// An action in flight (Provisioning/Starting/Terminating/…) or a server still setting
	// up offers only reads, mirroring the API which rejects a second command mid-flight.
	const settingUp = isSettingUp(props.server.status)
	const canChange =
		!props.server.pending_action &&
		!settingUp &&
		!isTerminated(props.server.status)
	const groups: DropdownOption[][] = [
		getViewActions(settingUp || !!props.server.pending_action),
		props.server.pending_action ? [] : getPowerActions(),
		canChange ? getChangeActions() : [],
		[{ label: 'Copy server ID', icon: 'lucide-copy', onClick: copyServerId }],
		canChange && allowed.value.terminate
			? [
					{
						label: 'Terminate',
						icon: 'lucide-trash-2',
						theme: 'red',
						onClick: () => emit('terminate', props.server),
					},
				]
			: [],
	]
	return groups
		.filter((items) => items.length)
		.map((items, index) => ({
			group: `${index}`,
			hideLabel: true,
			options: items,
		}))
})
</script>

<template>
	<RowActionsMenu
		:options="options"
		label="Server actions"
		:busy="busy || opening"
	/>
</template>
