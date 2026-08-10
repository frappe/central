<script setup lang="ts">
import { Avatar, Button, TabButtons } from 'frappe-ui'
import { computed, ref } from 'vue'

import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import RoleBuilderDialog from '@/components/team/RoleBuilderDialog.vue'
import RoleCapabilitiesPanel from '@/components/team/RoleCapabilitiesPanel.vue'
import RoleRowActions from '@/components/team/RoleRowActions.vue'

import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { useTeamRowSelection } from '@/composables/useTeamRowSelection'
import { roleDisplay } from '@/lib/roles'
import type { TeamMemberRow, TeamRoleRow } from '@/types/api'

const tab = defineModel<string>('tab', { default: 'roles' })
const tabs = [
	{ label: 'Team', value: 'team' },
	{ label: 'Roles', value: 'roles' },
]

const newRoleDialog = ref(false)
const { roles, loading, error, reload, deleteRole } = useTeamRoles()
const { members } = useTeamMembers()
const { canManageMembers } = useCapabilities()

const query = ref(createListViewQuery())
const deletingName = ref('')

// Role doc name -> members holding it, for the avatar stack in the Members column.
const membersByRole = computed<Record<string, TeamMemberRow[]>>(() => {
	const map: Record<string, TeamMemberRow[]> = {}
	for (const member of members.value) {
		const uniqueRoles = new Set(member.roles.map((grant) => grant.role))
		for (const role of uniqueRoles) {
			;(map[role] ??= []).push(member)
		}
	}
	return map
})

const roleMembers = (role: TeamRoleRow): TeamMemberRow[] =>
	membersByRole.value[role.name] ?? []

const onDeleteRole = async (role: TeamRoleRow): Promise<void> => {
	deletingName.value = role.name

	try {
		await deleteRole(role.name, role.role_name)
	} finally {
		deletingName.value = ''
	}
}

// Columns declare id/header/sorting only — the Role/Members/Actions markup is
// filled in by the matching #role/#members/#actions slots in the template below.
const columns = computed<ListViewColumn<TeamRoleRow>[]>(() => [
	{
		id: 'role',
		header: 'Role',
		accessorKey: 'role_name',
		meta: { cellClass: 'truncate' },
	},
	{
		id: 'members',
		header: 'Members',
		enableSorting: false,
	},
	{
		id: 'actions',
		header: '',
		enableSorting: false,
		size: 1,
		meta: { align: 'end' },
	},
])

const getRoleKey = (role: TeamRoleRow): string => role.name

// Clicking a role opens its capabilities — the definitive "what does this role
// mean" view. Selection resolves through `roles`, so a deleted role (or a team
// switch) closes the panel on its own.
const { selectedKey, selected, select, clear } = useTeamRowSelection(
	roles,
	getRoleKey,
)
</script>

<template>
	<ListView
		v-model:query="query"
		:rows="roles"
		:columns="columns"
		:row-key="getRoleKey"
		:loading="loading"
		:error="error"
		searchable
		search-placeholder="Search roles..."
		item-label="role"
		:show-count="false"
		:active-key="selectedKey"
		:empty-state="{ title: 'No roles yet', description: 'Create a role to grant capabilities to members.' }"
		@retry="reload"
		@row-click="select"
	>
		<template #toolbar>
			<TabButtons :options="tabs" v-model="tab" />
			<Button
				v-if="canManageMembers"
				variant="subtle"
				label="New role"
				icon-left="lucide-plus"
				@click="newRoleDialog = true"
			/>
		</template>

		<template #role="{ row }">
			<div class="flex min-w-0 items-center gap-3">
				<div
					class="flex size-8 shrink-0 items-center justify-center rounded-md bg-surface-gray-2 text-ink-gray-6"
				>
					<span :class="`${roleDisplay(row).icon} size-4`" aria-hidden="true" />
				</div>

				<div class="min-w-0">
					<p class="truncate font-medium text-ink-gray-9">
						{{ row.role_name }}
					</p>
					<p class="truncate text-p-sm text-ink-gray-5">
						{{ roleDisplay(row).description }}
					</p>
				</div>
			</div>
		</template>

		<template #members="{ row }">
			<div class="flex items-center">
				<Avatar
					v-for="member in roleMembers(row).slice(0, 5)"
					:key="member.user"
					:label="member.full_name"
					class="-ml-2 border-2 border-outline-base first:ml-0"
				/>
				<div
					v-if="roleMembers(row).length > 5"
					class="-ml-2 flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-outline-base bg-surface-gray-2 text-xs text-ink-gray-6"
				>
					+{{ roleMembers(row).length - 5 }}
				</div>
			</div>
		</template>

		<template #actions="{ row }">
			<RoleRowActions
				:role="row"
				:can-manage="canManageMembers"
				:busy="deletingName === row.name"
				@delete="onDeleteRole"
			/>
		</template>
	</ListView>

	<RoleCapabilitiesPanel
		:role="selected"
		@update:role="(v: TeamRoleRow | null) => !v && clear()"
	/>

	<RoleBuilderDialog v-model:open="newRoleDialog" @created="reload" />
</template>

<style scoped>
/* Same row height as the members list, so switching tabs doesn't change
   the list's rhythm. */
:deep([role='rowgroup'] > [role='row']) {
	height: auto;
	min-height: 4rem;
	padding-block: 0.5rem;
}
</style>
