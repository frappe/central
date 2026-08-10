<script setup lang="ts">
import { type DropdownOptions } from 'frappe-ui'
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { TeamMemberRow } from '@/types/api'

const props = defineProps<{
	member: TeamMemberRow
	canManage: boolean
	/** Current user is the team owner — enables transfer on other members. */
	isOwner: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	manageAccess: [member: TeamMemberRow]
	transferRequested: [member: TeamMemberRow]
	removeRequested: [member: TeamMemberRow]
}>()

const options = computed<DropdownOptions>(() => {
	if (props.member.is_owner) return []

	const items: DropdownOptions = []

	if (props.canManage) {
		items.push({
			label: 'Manage access',
			icon: 'lucide-shield',
			onClick: () => emit('manageAccess', props.member),
		})
	}

	if (props.isOwner && props.member.status === 'Active') {
		items.push({
			label: 'Transfer ownership',
			icon: 'lucide-crown',
			onClick: () => emit('transferRequested', props.member),
		})
	}

	if (props.canManage) {
		items.push({
			label: 'Remove from team',
			icon: 'lucide-user-x',
			theme: 'red',
			onClick: () => emit('removeRequested', props.member),
		})
	}

	return items
})
</script>

<template>
	<RowActionsMenu :options="options" label="Member actions" :busy="busy" />
</template>
