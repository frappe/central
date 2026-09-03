<script setup lang="ts">
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { Project } from '@/types/billing'

// The management menu for one Project row — mirrors SubscriptionRowActions.
// Disabling isn't destructive (its subscriptions just stop showing under this
// project's heading in the cost breakdown; they aren't untagged — generate.py
// re-groups them the moment the project is re-enabled), so it needs no confirm
// step, unlike removing a payment method or pausing a subscription.
// Presentational: emits the chosen verb.
const props = defineProps<{
	project: Project
	canManage: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	rename: [project: Project]
	toggle: [project: Project]
	manageMembers: [project: Project]
}>()

interface ActionItem {
	label: string
	icon: string
	onClick: () => void
}

const options = computed<ActionItem[]>(() => {
	if (!props.canManage) return []
	return [
		{
			label: 'Manage servers',
			icon: 'lucide-server',
			onClick: () => emit('manageMembers', props.project),
		},
		{ label: 'Edit', icon: 'lucide-pencil', onClick: () => emit('rename', props.project) },
		{
			label: props.project.enabled ? 'Disable' : 'Enable',
			icon: props.project.enabled ? 'lucide-pause' : 'lucide-play',
			onClick: () => emit('toggle', props.project),
		},
	]
})
</script>

<template>
	<RowActionsMenu
		:options="options"
		label="Project actions"
		icon="lucide-ellipsis"
		:busy="busy"
	/>
</template>
