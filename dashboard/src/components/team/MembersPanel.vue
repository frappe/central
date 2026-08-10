<script setup lang="ts">
import { Avatar, Badge, Button, TabButtons, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import RightSidebar from '@/components/common/RightSidebar.vue'

import CapabilityList from '@/components/team/CapabilityList.vue'
import InviteMemberDialog from '@/components/team/InviteMemberDialog.vue'
import ManageRolesDialog from '@/components/team/ManageRolesDialog.vue'
import RemoveMemberDialog from '@/components/team/RemoveMemberDialog.vue'
import TeamMemberRowActions from '@/components/team/TeamMemberRowActions.vue'

import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { useTeamRowSelection } from '@/composables/useTeamRowSelection'
import { useTeamSettings } from '@/composables/useTeamSettings'
import { teamParams } from '@/composables/useTeamScope'
import {
	resourceScopeLabel,
	resourceTypeIcon,
	roleOnResourceLabel,
} from '@/lib/resourceScope'
import {
	roleAvatarTheme,
	roleDisplayByName,
} from '@/lib/roles'
import type { TeamMemberRow, TeamRegistry } from '@/types/api'

const tab = defineModel<string>('tab', { default: 'team' })
const tabs = [
	{ label: 'Team', value: 'team' },
	{ label: 'Roles', value: 'roles' },
]

const inviteDialog = ref(false)
const manageAccessFor = ref<TeamMemberRow | null>(null)
const removeTarget = ref<TeamMemberRow | null>(null)
const transferTarget = ref<TeamMemberRow | null>(null)

const { members, loading, error, busy, reload } = useTeamMembers()
const { roles, capabilities, capsByRole, roleLabel } = useTeamRoles()
const { canManageMembers } = useCapabilities()
const { isOwner, saving, transferOwnership } = useTeamSettings()

const registryCall = useCall<TeamRegistry, { team: string }>({
	url: method(API.registry),
	params: teamParams,
	immediate: false,
})

watch(
	members,
	(list) => {
		if (list.length && !registryCall.data) registryCall.reload()
	},
	{ immediate: true },
)

const registry = computed(() => registryCall.data)

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

function primaryRoleTheme(member: TeamMemberRow) {
	const grant = member.roles[0]
	if (!grant) return 'gray' as const
	return roleAvatarTheme(roleDisplayByName(roles.value, grant.role).theme)
}

const columns = computed<ListViewColumn<TeamMemberRow>[]>(() => [
	{
		id: 'member',
		header: 'Member',
		accessorFn: (member) => `${member.full_name} ${member.user}`,
		meta: { cellClass: 'truncate' },
	},
	{
		id: 'access',
		header: 'Access',
		accessorFn: (member) =>
			member.roles
				.map((grant) =>
					roleOnResourceLabel(roleLabel(grant.role), grant, registry.value),
				)
				.join(', '),
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

async function onTransfer(member: TeamMemberRow): Promise<void> {
	if (await transferOwnership(member.user)) transferTarget.value = null
}
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
		:empty-state="{
			title: 'No members yet',
			description: 'Invite someone to share access to this team’s resources.',
		}"
		@retry="reload"
		@row-click="select"
	>
		<template #toolbar>
			<TabButtons :options="tabs" v-model="tab" />
			<Button
				v-if="canManageMembers"
				variant="subtle"
				label="Invite"
				icon-left="lucide-user-plus"
				@click="inviteDialog = true"
			/>
		</template>

		<template #member="{ row }">
			<div class="flex min-w-0 items-center gap-3">
				<Avatar :label="row.full_name" size="md" :theme="primaryRoleTheme(row)" />
				<div class="min-w-0">
					<div class="flex items-center gap-2">
						<p class="truncate font-medium text-ink-gray-9">
							{{ row.full_name }}
						</p>
						<Badge v-if="row.is_owner" theme="green" label="Owner" />
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

		<template #access="{ row }">
			<div class="flex min-w-0 flex-col gap-1">
				<div
					v-for="grant in row.roles.slice(0, 3)"
					:key="`${grant.role}::${grant.resource_type}::${grant.resource_name}`"
					class="flex min-w-0 items-center gap-2"
				>
					<span
						:class="[
							roleDisplayByName(roles, grant.role).icon,
							'size-3.5 shrink-0 text-ink-gray-5',
						]"
						aria-hidden="true"
					/>
					<p class="truncate text-p-sm text-ink-gray-8">
						<span class="font-medium">{{ roleLabel(grant.role) }}</span>
						<span class="text-ink-gray-5">
							on {{ resourceScopeLabel(grant, registry) }}
						</span>
					</p>
				</div>
				<p v-if="row.roles.length > 3" class="text-p-sm text-ink-gray-5">
					+{{ row.roles.length - 3 }} more
				</p>
				<p v-if="!row.roles.length" class="text-p-sm text-ink-gray-5">
					No access grants
				</p>
			</div>
		</template>

		<template #actions="{ row }">
			<TeamMemberRowActions
				:member="row"
				:can-manage="canManageMembers"
				:is-owner="isOwner"
				:busy="busy === row.user || (saving && transferTarget?.user === row.user)"
				@manage-access="manageAccessFor = $event"
				@transfer-requested="transferTarget = $event"
				@remove-requested="removeTarget = $event"
			/>
		</template>
	</ListView>

	<RightSidebar
		:open="!!selected"
		:title="selected?.full_name"
		:subtitle="selected?.user"
		@close="clear"
	>
		<div v-if="selected" class="flex flex-col gap-6">
			<section class="flex flex-col gap-3">
				<div class="flex items-center justify-between gap-2">
					<h3 class="text-sm font-medium text-ink-gray-9">Access</h3>
					<Button
						v-if="canManageMembers && !selected.is_owner"
						variant="subtle"
						label="Edit"
						icon-left="lucide-shield"
						@click="manageAccessFor = selected"
					/>
				</div>

				<ul v-if="selected.roles.length" class="flex flex-col gap-2">
					<li
						v-for="grant in selected.roles"
						:key="`${grant.role}::${grant.resource_type}::${grant.resource_name}`"
						class="flex items-start gap-3 rounded-md bg-surface-gray-1 px-3 py-2.5"
					>
						<span
							:class="[
								resourceTypeIcon(grant.resource_type),
								'mt-0.5 size-4 shrink-0 text-ink-gray-5',
							]"
							aria-hidden="true"
						/>
						<div class="min-w-0">
							<p class="truncate text-sm font-medium text-ink-gray-9">
								{{ roleLabel(grant.role) }}
							</p>
							<p class="truncate text-p-sm text-ink-gray-5">
								{{ resourceScopeLabel(grant, registry) }}
							</p>
						</div>
					</li>
				</ul>
				<p v-else class="text-p-sm text-ink-gray-5">No role grants yet.</p>
			</section>

			<section>
				<h3 class="mb-3 text-sm font-medium text-ink-gray-9">Capabilities</h3>
				<CapabilityList :caps="selectedRoleCaps" :palette="capabilities" />
			</section>
		</div>

		<template v-if="selected && canManageMembers && !selected.is_owner" #footer>
			<Button
				class="w-full"
				variant="subtle"
				label="Manage access"
				icon-left="lucide-shield"
				@click="manageAccessFor = selected"
			/>
		</template>
	</RightSidebar>

	<InviteMemberDialog v-model:open="inviteDialog" />
	<ManageRolesDialog v-model:member="manageAccessFor" />
	<RemoveMemberDialog v-model:member="removeTarget" />
	<ConfirmDialog
		v-model:target="transferTarget"
		title="Transfer ownership"
		:message="
			transferTarget
				? `Make ${transferTarget.full_name} the owner of this team? You will become an Admin.`
				: ''
		"
		confirm-label="Transfer ownership"
		:loading="saving"
		@confirm="onTransfer"
	/>
</template>

<style scoped>
:deep([role='rowgroup'] > [role='row']) {
	height: auto;
	min-height: 3.25rem;
	padding-block: 0.375rem;
}
</style>
