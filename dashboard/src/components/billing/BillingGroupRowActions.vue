<script setup lang="ts">
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { BillingGroup } from '@/types/billing'

// The management menu for one Billing Group row — mirrors SubscriptionRowActions.
// Disabling isn't destructive (its subscriptions fold back onto the consolidated
// invoice, they aren't untagged — generate.py re-partitions them the moment the
// group is re-enabled), so it needs no confirm step, unlike removing a payment
// method or pausing a subscription. Presentational: emits the chosen verb.
const props = defineProps<{
	group: BillingGroup
	canManage: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	rename: [group: BillingGroup]
	toggle: [group: BillingGroup]
	manageMembers: [group: BillingGroup]
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
			onClick: () => emit('manageMembers', props.group),
		},
		{ label: 'Rename', icon: 'lucide-pencil', onClick: () => emit('rename', props.group) },
		{
			label: props.group.enabled ? 'Disable' : 'Enable',
			icon: props.group.enabled ? 'lucide-pause' : 'lucide-play',
			onClick: () => emit('toggle', props.group),
		},
	]
})
</script>

<template>
	<RowActionsMenu
		:options="options"
		label="Billing group actions"
		icon="lucide-ellipsis"
		:busy="busy"
	/>
</template>
