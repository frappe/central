<script setup lang="ts">
import { Avatar, Badge, Button, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import InvitationRowActions from '@/components/team/InvitationRowActions.vue'
import InviteMemberDialog from '@/components/team/InviteMemberDialog.vue'
import ManageRolesDialog from '@/components/team/ManageRolesDialog.vue'
import RemoveMemberDialog from '@/components/team/RemoveMemberDialog.vue'
import TeamMemberRowActions from '@/components/team/TeamMemberRowActions.vue'
import TransferOwnershipDialog from '@/components/team/TransferOwnershipDialog.vue'

import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamInvitations } from '@/composables/useTeamInvitations'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { useTeamSettings } from '@/composables/useTeamSettings'
import { teamParams } from '@/composables/useTeamScope'
import { formatDate } from '@/lib/format'
import { resourceScopeLabel, roleOnResourceLabel } from '@/lib/resourceScope'
import type {
	InvitationRow,
	TeamMemberRoleAssignment,
	TeamMemberRow,
	TeamRegistry,
} from '@/types/api'

const inviteDialog = ref(false)
const manageAccessFor = ref<TeamMemberRow | null>(null)
const removeTarget = ref<TeamMemberRow | null>(null)
const transferTarget = ref<TeamMemberRow | null>(null)

const { members, loading, error, busy, reload } = useTeamMembers()
const {
	invitations,
	busy: inviteBusy,
	reload: reloadInvites,
	resend,
	revoke,
} = useTeamInvitations()

const { roles, roleLabel } = useTeamRoles()
const { canManageMembers } = useCapabilities()
const { isOwner } = useTeamSettings()

// Grants name concrete resources, so the scope labels need the registry to
// turn ids into titles. Fetched once the roster is worth labelling.
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

// One roster: people who are in the team, plus the ones on their way. A pending
// invite is the same shape as a member row so the list sorts, searches and reads
// as a single thing — it just can't be acted on the same way.
interface RosterRow {
	key: string
	name: string
	subtitle: string
	roles: TeamMemberRoleAssignment[]
	member: TeamMemberRow | null
	invite: InvitationRow | null
}

const roster = computed<RosterRow[]>(() => [
	...members.value.map((member) => ({
		key: member.user,
		name: member.full_name,
		subtitle: member.user,
		roles: member.roles,
		member,
		invite: null,
	})),
	...invitations.value
		.filter((invite) => invite.status === 'Pending')
		.map((invite) => ({
			key: invite.name,
			// No name until they accept, so the address is the identity.
			name: invite.email,
			subtitle: invite.expires_on
				? `Expires ${formatDate(invite.expires_on)}`
				: 'Invite sent',
			// Invitations are resource-scoped too, so the grant carries the
			// invite's own scope into the Access column.
			roles: [
				{
					role: invite.role,
					resource_type: invite.resource_type ?? '*',
					resource_name: invite.resource_name ?? null,
				},
			],
			member: null,
			invite,
		})),
])

const query = ref(
	createListViewQuery({
		pageSize: 20,
		sort: { key: 'access', direction: 'asc' },
	}),
)

const getRowKey = (row: RosterRow): string => row.key

// Owner first, then Admins, then everyone else — and people who haven't joined
// yet after all of them.
const roleNames = (row: RosterRow): string =>
	row.roles.map((grant) => roleLabel(grant.role)).join(', ')

function memberRank(row: RosterRow): number {
	if (row.invite) return 4
	const ranks = row.roles.map((grant) => {
		const label = roleLabel(grant.role)
		if (label === 'Owner') return 0
		if (label === 'Admin') return 1
		return 2
	})
	return ranks.length ? Math.min(...ranks) : 3
}

// Columns declare id/header/sorting only — the Member/Access/Actions markup is
// filled in by the matching slots in the template below.
const columns = computed<ListViewColumn<RosterRow>[]>(() => [
	{
		id: 'member',
		header: 'Member',
		accessorFn: (row) => `${row.name} ${row.member?.user ?? ''}`,
		meta: { cellClass: 'truncate' },
	},
	{
		id: 'access',
		header: 'Access',
		// The accessor is what search and the role filter match on, so it stays
		// the plain "Role · scope" text; ranking lives in sortingFn instead, or
		// "1" would find every Admin.
		accessorFn: (row) =>
			row.roles
				.map((grant) =>
					roleOnResourceLabel(roleLabel(grant.role), grant, registry.value),
				)
				.join(', '),
		sortingFn: (a, b) =>
			memberRank(a.original) - memberRank(b.original) ||
			roleNames(a.original).localeCompare(roleNames(b.original)),
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

// Filter the roster by role. Options come from the team's own role list, and
// the values are the same display labels the access accessor renders, so the
// (substring) column filter matches multi-role and scoped rows too.
const roleFilters = computed<ListViewFilter[]>(() => [
	{
		key: 'access',
		label: 'Roles',
		allLabel: 'All roles',
		options: [...new Set(roles.value.map((role) => roleLabel(role.name)))].map(
			(label) => ({ label, value: label }),
		),
	},
])
</script>

<template>
	<ListView
		v-model:query="query"
		:rows="roster"
		:columns="columns"
		:row-key="getRowKey"
		:loading="loading"
		:error="error"
		searchable
		search-placeholder="Search members by name, email"
		:filters="roleFilters"
		item-label="member"
		:show-count="false"
		:empty-state="{
			title: 'No members yet',
			description: 'Invite someone to share access to this team\'s resources.',
		}"
		@retry="reload"
	>
		<!-- The page's view switcher rides on the controls row, ahead of search. -->
		<template #controls-start>
			<slot name="controls-start" />
		</template>

		<template #toolbar>
			<Button
				v-if="canManageMembers"
				variant="solid"
				label="Invite"
				icon-left="lucide-user-plus"
				@click="inviteDialog = true"
			/>
		</template>

		<template #member="{ row }">
			<div class="flex min-w-0 items-center gap-3">
				<!-- An invite has no face yet, so its avatar stays a plain tint. -->
				<Avatar
					:image="row.member?.user_image ?? undefined"
					:label="row.name"
					size="md"
					:class="row.invite ? 'opacity-60' : ''"
				/>
				<div class="min-w-0">
					<div class="flex items-center gap-2">
						<p class="truncate font-medium text-ink-gray-9">{{ row.name }}</p>
						<Badge v-if="row.invite" theme="orange" label="Invited" />
						<Badge
							v-else-if="row.member?.status === 'Suspended'"
							theme="red"
							label="Suspended"
						/>
					</div>
					<p class="truncate text-p-sm text-ink-gray-5">{{ row.subtitle }}</p>
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
			<InvitationRowActions
				v-if="row.invite"
				:invitation="row.invite"
				:can-manage="canManageMembers"
				:busy="inviteBusy === row.invite.name"
				@resend="resend"
				@revoke="revoke"
			/>
			<TeamMemberRowActions
				v-else-if="row.member"
				:member="row.member"
				:can-manage="canManageMembers"
				:is-owner="isOwner"
				:busy="busy === row.member.user"
				@manage-access="manageAccessFor = $event"
				@transfer-requested="transferTarget = $event"
				@remove-requested="removeTarget = $event"
			/>
		</template>
	</ListView>


	<!-- A fresh invite has to land in the roster right away — that's the point. -->
	<InviteMemberDialog v-model:open="inviteDialog" @invited="reloadInvites" />
	<ManageRolesDialog v-model:member="manageAccessFor" />
	<RemoveMemberDialog v-model:member="removeTarget" />
	<TransferOwnershipDialog v-model:member="transferTarget" />
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
