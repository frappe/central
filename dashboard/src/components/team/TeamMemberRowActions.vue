<script setup lang="ts">
import { type DropdownOptions } from 'frappe-ui'
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { TeamMemberRow } from '@/types/api'

const props = defineProps<{
	member: TeamMemberRow
	canManage: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	manageRoles: [member: TeamMemberRow]
	removeRequested: [member: TeamMemberRow]
}>()

const options = computed<DropdownOptions>(() => {
	if (!props.canManage || props.member.is_owner) return []

	return [
		{
			label: 'Manage roles',
			icon: 'lucide-shield',
			onClick: () => emit('manageRoles', props.member),
		},
		{
			label: 'Remove from team',
			icon: 'lucide-user-x',
			theme: 'red',
			onClick: () => emit('removeRequested', props.member),
		},
	]
})
</script>

<template>
	<RowActionsMenu :options="options" label="Member actions" :busy="busy" />
</template>
