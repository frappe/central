<script setup lang="ts">
import { computed, ref } from 'vue'
import { Avatar, Badge, Button } from 'frappe-ui'
import RightSidebar from '@/components/common/RightSidebar.vue'

import {
	ListView,
	createListViewQuery,
	type ListViewColumn,
} from '@/components/common/list-view'

import CapabilityList from '@/components/team/CapabilityList.vue'
import TeamMemberRowActions from '@/components/team/TeamMemberRowActions.vue'
import InviteMemberDialog from '@/components/team/InviteMemberDialog.vue'

import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { useTeamRowSelection } from '@/composables/useTeamRowSelection'
import { roleDisplayByName } from '@/lib/roles'
import type { TeamMemberRow } from '@/types/api'

const inviteDialog = ref(false)

const { members, loading, error, busy, reload, setRole, setStatus, remove } =
	useTeamMembers()

const { roles, capabilities, capsByRole, roleLabel } = useTeamRoles()
const { canManageMembers } = useCapabilities()

const query = ref(
	createListViewQuery({
		pageSize: 20,
		sort: { key: 'member', direction: 'asc' },
	}),
)

const getMemberKey = (member: TeamMemberRow): string => member.user

const { selected, select, clear } = useTeamRowSelection(members, getMemberKey)

const selectedRoleCaps = computed(() =>
	selected.value ? (capsByRole.value[selected.value.role] ?? []) : [],
)

// Columns declare id/header/sorting only — the Member/Role/Actions markup is
// filled in by the matching #member/#role/#actions slots in the template below.
const columns = computed<ListViewColumn<TeamMemberRow>[]>(() => [
	{
		id: 'member',
		header: 'Member',
		accessorFn: (member) => `${member.full_name} ${member.user}`,
		meta: { cellClass: 'truncate' },
	},
	{
		id: 'role',
		header: 'Role',
		accessorFn: (member) => roleLabel(member.role),
		meta: { cellClass: 'truncate' },
	},
	{
		id: 'actions',
		header: '',
		enableSorting: false,
		size: 1,
		meta: { align: 'end' },
	},
])

</script>

<template>
	<ListView
		v-model:query="query"
		:rows="members"
		:columns="columns"
		:row-key="getMemberKey"
		:loading="loading"
		:error="error"
		searchable
		search-placeholder="Search members by name, email"
		item-label="member"
		:empty-state="{ title: 'No members yet', description: 'The active team roster is empty.' }"
		@retry="reload"
		@row-click="select"
	>
		<template #toolbar>
			<Button
				v-if="canManageMembers"
				variant="solid"
				label="Invite"
				icon-left="lucide-user-plus"
				@click="inviteDialog = true"
			/>
		</template>

		<template #member="{ row }: { row: TeamMemberRow }">
			<div class="flex min-w-0 items-center gap-3">
				<Avatar :label="row.full_name" size="md" />
				<div class="min-w-0">
					<div class="flex items-center gap-2">
						<p class="truncate font-medium text-ink-gray-9">
							{{ row.full_name }}
						</p>
						<Badge
							v-if="row.status === 'Suspended'"
							theme="red"
							label="Suspended"
						/>
					</div>
					<p class="truncate text-p-sm text-ink-gray-5">{{ row.user }}</p>
				</div>
			</div>
		</template>

		<template #role="{ row }: { row: TeamMemberRow }">
			<Badge
				:theme="roleDisplayByName(roles, row.role).theme"
				:label="roleLabel(row.role)"
			>
				<template #prefix>
					<span
						:class="`${roleDisplayByName(roles, row.role).icon} size-3`"
						aria-hidden="true"
					/>
				</template>
			</Badge>
		</template>

		<template #actions="{ row }: { row: TeamMemberRow }">
			<TeamMemberRowActions
				:member="row"
				:roles="roles"
				:can-manage="canManageMembers"
				:busy="busy === row.user"
				@set-role="setRole"
				@set-status="setStatus"
				@remove="remove"
			/>
		</template>
	</ListView>

	<RightSidebar
		:open="!!selected"
		:title="selected?.full_name"
		:subtitle="selected ? roleLabel(selected.role) : ''"
		@close="clear"
	>
		<div v-if="selected" class="space-y-6">
			<section>
				<CapabilityList :caps="selectedRoleCaps" :palette="capabilities" />
			</section>
		</div>
	</RightSidebar>

	<InviteMemberDialog v-model:open="inviteDialog" />
</template>

<style scoped>
/* Body rows need room for an avatar + two stacked lines (name, email); the
   shared ListView otherwise renders a fixed single-line h-10 row. Scoped to
   this panel's rowgroup only — the header row sits outside it. */
:deep([role="rowgroup"] > [role="row"]) {
	height: auto;
	min-height: 4rem;
	padding-block: 0.5rem;
}
</style>
