<script setup lang="ts">
import { Button, Dropdown, type DropdownOptions } from 'frappe-ui'
import { computed } from 'vue'
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
	<Dropdown v-if="options.length" :options="options" placement="right">
		<template #trigger>
			<Button
				variant="ghost"
				icon="lucide-ellipsis-vertical"
				:loading="busy"
				aria-label="Member actions"
				@click.stop
			/>
		</template>
	</Dropdown>
</template>
