<script setup lang="ts">
import { Badge, Button } from 'frappe-ui'
import { computed, h, ref } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import RightSidebar from '@/components/common/RightSidebar.vue'
import CapabilityList from '@/components/team/CapabilityList.vue'
import InviteMemberDialog from '@/components/team/InviteMemberDialog.vue'
import TeamMemberRowActions from '@/components/team/TeamMemberRowActions.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { useTeamRowSelection } from '@/composables/useTeamRowSelection'
import type { TeamMemberRow } from '@/types/api'

const { members, loading, error, busy, reload, setRole, setStatus, remove } =
	useTeamMembers()
const { roles, capabilities, capsByRole, roleLabel } = useTeamRoles()
const { canManageMembers } = useCapabilities()

const query = ref(
	createListViewQuery({
		pageSize: 20,
		sort: { key: 'user', direction: 'asc' },
	}),
)
const inviteOpen = ref(false)
const { selected, select, clear } = useTeamRowSelection(members, getMemberKey)

const selectedRoleCaps = computed(() =>
	selected.value ? (capsByRole.value[selected.value.role] ?? []) : [],
)

const filters: ListViewFilter[] = [
	{
		key: 'status',
		label: 'Status',
		options: [
			{ label: 'Active', value: 'Active' },
			{ label: 'Suspended', value: 'Suspended' },
		],
	},
]

const columns = computed<ListViewColumn<TeamMemberRow>[]>(() => [
	{
		accessorKey: 'user',
		header: 'Member',
		meta: { cellClass: 'truncate font-medium' },
	},
	{
		id: 'role',
		header: 'Role',
		accessorFn: (member) => roleLabel(member.role),
		meta: { cellClass: 'truncate' },
	},
	{
		accessorKey: 'status',
		header: 'Status',
		enableSorting: false,
		cell: ({ row }) =>
			h('div', { class: 'flex items-center gap-2' }, [
				h(Badge, {
					theme: row.original.status === 'Active' ? 'green' : 'orange',
					label: row.original.status,
				}),
				row.original.is_owner
					? h(Badge, { theme: 'gray', label: 'Owner' })
					: null,
			]),
	},
	{
		id: 'actions',
		header: '',
		enableSorting: false,
		size: 1,
		meta: { align: 'end' },
		cell: ({ row }) =>
			h(TeamMemberRowActions, {
				member: row.original,
				roles: roles.value,
				canManage: canManageMembers.value,
				busy: busy.value === row.original.user,
				onSetRole: setRole,
				onSetStatus: setStatus,
				onRemove: remove,
			}),
	},
])

function getMemberKey(member: TeamMemberRow): string {
	return member.user
}
</script>

<template>
	<div class="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
		<ListView
			class="mx-auto flex h-full max-w-4xl flex-col"
			v-model:query="query"
			:rows="members"
			:columns="columns"
			:row-key="getMemberKey"
			:loading="loading"
			:error="error"
			:filters="filters"
			searchable
			search-placeholder="Search members..."
			item-label="member"
			:empty-state="{ title: 'No members yet', description: 'The active team roster is empty.' }"
			@retry="reload"
			@row-click="select"
		>
			<template v-if="canManageMembers" #toolbar>
				<Button
					variant="solid"
					label="Invite"
					icon-left="lucide-user-plus"
					@click="inviteOpen = true"
				/>
			</template>
		</ListView>
	</div>

	<RightSidebar
		:open="!!selected"
		:title="selected?.user"
		:subtitle="selected ? roleLabel(selected.role) : ''"
		@close="clear"
	>
		<div v-if="selected" class="space-y-6">
			<section>
				<CapabilityList :caps="selectedRoleCaps" :palette="capabilities" />
			</section>
		</div>
	</RightSidebar>

	<InviteMemberDialog v-model:open="inviteOpen" />
</template>
