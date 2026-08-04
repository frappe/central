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
import ManageRolesDialog from '@/components/team/ManageRolesDialog.vue'
import RemoveMemberDialog from '@/components/team/RemoveMemberDialog.vue'

import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { useTeamRowSelection } from '@/composables/useTeamRowSelection'
import { roleDisplayByName } from '@/lib/roles'
import type { TeamMemberRow } from '@/types/api'

const inviteDialog = ref(false)
const manageRolesFor = ref<TeamMemberRow | null>(null)
const removeTarget = ref<TeamMemberRow | null>(null)

const { members, loading, error, busy, reload } = useTeamMembers()

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

const selectedRoleCaps = computed(() => {
	if (!selected.value) return []
	const caps = new Set<string>()
	for (const grant of selected.value.roles) {
		for (const cap of capsByRole.value[grant.role] ?? []) caps.add(cap)
	}
	return [...caps]
})

// Columns declare id/header/sorting only — the Member/Roles/Actions markup is
// filled in by the matching #member/#roles/#actions slots in the template below.
const columns = computed<ListViewColumn<TeamMemberRow>[]>(() => [
	{
		id: 'member',
		header: 'Member',
		accessorFn: (member) => `${member.full_name} ${member.user}`,
		meta: { cellClass: 'truncate' },
	},
	{
		id: 'roles',
		header: 'Roles',
		accessorFn: (member) => member.roles.map((r) => roleLabel(r.role)).join(', '),
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

		<template #roles="{ row }: { row: TeamMemberRow }">
			<div class="flex flex-wrap items-center gap-1">
				<Badge
					v-for="grant in row.roles.slice(0, 2)"
					:key="`${grant.role}::${grant.resource_type}::${grant.resource_name}`"
					:theme="roleDisplayByName(roles, grant.role).theme"
					:label="roleLabel(grant.role)"
				>
					<template #prefix>
						<span
							:class="`${roleDisplayByName(roles, grant.role).icon} size-3`"
							aria-hidden="true"
						/>
					</template>
				</Badge>
				<Badge
					v-if="row.roles.length > 2"
					theme="gray"
					:label="`+${row.roles.length - 2}`"
				/>
			</div>
		</template>

		<template #actions="{ row }: { row: TeamMemberRow }">
			<TeamMemberRowActions
				:member="row"
				:can-manage="canManageMembers"
				:busy="busy === row.user"
				@manage-roles="manageRolesFor = $event"
				@remove-requested="removeTarget = $event"
			/>
		</template>
	</ListView>

	<RightSidebar
		:open="!!selected"
		:title="selected?.full_name"
		:subtitle="selected ? selected.roles.map((r) => roleLabel(r.role)).join(', ') : ''"
		@close="clear"
	>
		<div v-if="selected" class="space-y-6">
			<section>
				<CapabilityList :caps="selectedRoleCaps" :palette="capabilities" />
			</section>
		</div>
	</RightSidebar>

	<InviteMemberDialog v-model:open="inviteDialog" />
	<ManageRolesDialog v-model:member="manageRolesFor" />
	<RemoveMemberDialog v-model:member="removeTarget" />
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
