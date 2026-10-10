<script setup lang="ts">
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import { getServerActions } from '@/lib/capabilities'
import { getServerMenu, type ServerMenuVerb } from '@/lib/serverMenu'

// The lifecycle menu for one server row. Presentational: it emits the chosen verb and
// the page owns the calls.
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

const handlers: Record<ServerMenuVerb, () => void> = {
	overview: () => emit('overview', props.server),
	open: () => emit('open', props.server),
	pilot: () => emit('pilot', props.server),
	start: () => emit('start', props.server),
	stop: () => emit('stop', props.server),
	restart: () => emit('restart', props.server),
	resize: () => emit('resize', props.server),
	snapshot: () => emit('snapshot', props.server),
	console: () => emit('console', props.server),
	terminate: () => emit('terminate', props.server),
}

const options = computed(() =>
	getServerMenu(
		props.server,
		getServerActions(props.server, {
			open: props.canOpen,
			power: props.canPower,
			resize: props.canResize,
			snapshot: !!props.canSnapshot,
			terminate: props.canTerminate,
			console: !!props.canOpenConsole,
		}),
		(verb: ServerMenuVerb) => handlers[verb](),
		{ opensSite: props.opensSite },
	),
)
</script>

<template>
	<RowActionsMenu
		:options="options"
		label="Server actions"
		:busy="busy || opening"
	/>
</template>
