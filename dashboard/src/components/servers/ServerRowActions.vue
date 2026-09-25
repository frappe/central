<script setup lang="ts">
import type { DropdownSide } from 'frappe-ui'
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import { getServerActions } from '@/lib/capabilities'
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
	/** Where the menu opens. The map card uses `right` so it sits beside the card. */
	side?: DropdownSide
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

interface ActionItem {
	label: string
	icon: string
	theme?: 'red'
	disabled?: boolean
	onClick: () => void
}

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

const options = computed(() => {
	const items: ActionItem[] = []
	items.push({
		label: 'Overview',
		icon: 'lucide-gauge',
		onClick: () => emit('overview', props.server),
	})
	// An action is in flight (Provisioning/Starting/Terminating/…): offer nothing else until
	// it settles, mirroring the API which rejects a second command mid-flight.
	if (props.server.pending_action) return items
	// Still provisioning — Open/Resize/Terminate wait until the VM leaves Setting up.
	const settingUp = isSettingUp(props.server.status)
	if (allowed.value.open && !settingUp)
		items.push({
			label: 'Open',
			icon: 'lucide-external-link',
			disabled:
				props.server.status !== 'Running' ||
				!(props.opensSite || props.server.gateway_url),
			onClick: () => emit('open', props.server),
		})
	// Open goes to the site on a site server, so Pilot admin needs its own entry.
	if (allowed.value.open && !settingUp && props.opensSite)
		items.push({
			label: 'Open Pilot',
			icon: 'lucide-layout-dashboard',
			disabled: props.server.status !== 'Running' || !props.server.gateway_url,
			onClick: () => emit('pilot', props.server),
		})
	if (allowed.value.console && props.server.image_offering === 'ubuntu')
		items.push({
			label: 'Web console',
			icon: 'lucide-terminal',
			disabled: props.server.status !== 'Running',
			onClick: () => emit('console', props.server),
		})
	if (allowed.value.power && canStart(props.server.status))
		items.push({
			label: 'Start',
			icon: 'lucide-play',
			onClick: () => emit('start', props.server),
		})
	if (allowed.value.power && canStop(props.server.status))
		items.push({
			label: 'Stop',
			icon: 'lucide-square',
			onClick: () => emit('stop', props.server),
		})
	// Only a running server can restart, and the API refuses it in any other state.
	if (allowed.value.power && canStop(props.server.status))
		items.push({
			label: 'Restart',
			icon: 'lucide-rotate-ccw',
			onClick: () => emit('restart', props.server),
		})
	// Resize compute; the dialog gates on a Stopped VM and slides a preset onto a
	// custom config.
	if (allowed.value.resize && !isTerminated(props.server.status) && !settingUp)
		items.push({
			label: 'Resize',
			icon: 'lucide-sliders-horizontal',
			onClick: () => emit('resize', props.server),
		})
	if (
		allowed.value.snapshot &&
		!isTerminated(props.server.status) &&
		!settingUp
	)
		items.push({
			label: 'Take snapshot',
			icon: 'lucide-camera',
			onClick: () => emit('snapshot', props.server),
		})
	if (
		allowed.value.terminate &&
		!isTerminated(props.server.status) &&
		!settingUp
	)
		items.push({
			label: 'Terminate',
			icon: 'lucide-trash-2',
			theme: 'red',
			onClick: () => emit('terminate', props.server),
		})
	return items
})
</script>

<template>
	<RowActionsMenu
		:options="options"
		label="Server actions"
		:busy="busy || opening"
		:side="side"
		:align="side === 'right' ? 'start' : 'end'"
	/>
</template>
