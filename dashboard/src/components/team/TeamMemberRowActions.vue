<script setup lang="ts">
import { computed } from 'vue'
import { Button, Dropdown, type DropdownOptions } from 'frappe-ui'
import type { MemberStatus, TeamMemberRow, TeamRoleRow } from '@/types/api'

const props = defineProps<{
	member: TeamMemberRow
	roles: TeamRoleRow[]
	canManage: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	setRole: [user: string, role: string]
	setStatus: [user: string, status: MemberStatus]
	remove: [user: string]
}>()

const assignableRoles = computed(() =>
	props.roles.filter(
		(role) => role.role_name !== 'Owner' && role.name !== props.member.role,
	),
)

const options = computed<DropdownOptions>(() => {
	if (!props.canManage || props.member.is_owner) return []

	const items: DropdownOptions = []
	if (assignableRoles.value.length) {
		items.push({
			group: 'Change role',
			options: assignableRoles.value.map((role) => ({
				label: role.role_name,
				onClick: () => emit('setRole', props.member.user, role.name),
			})),
		})
	}

	items.push({
		group: 'Membership',
		options: [
			{
				label: props.member.status === 'Active' ? 'Suspend' : 'Reactivate',
				icon:
					props.member.status === 'Active'
						? 'lucide-circle-pause'
						: 'lucide-circle-play',
				onClick: () =>
					emit(
						'setStatus',
						props.member.user,
						props.member.status === 'Active' ? 'Suspended' : 'Active',
					),
			},
			{
				label: 'Remove',
				icon: 'lucide-user-x',
				theme: 'red',
				onClick: () => emit('remove', props.member.user),
			},
		],
	})
	return items
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
