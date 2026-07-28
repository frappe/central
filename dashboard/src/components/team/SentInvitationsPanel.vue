<script setup lang="ts">
import { computed, h, ref } from "vue";
import { Badge, Button } from "frappe-ui";
import {
	ListView,
	createListViewQuery,
	type ListViewColumn,
	type ListViewFilter,
} from "@/components/common/list-view";
import InvitationRowActions from "@/components/team/InvitationRowActions.vue";
import InviteMemberDialog from "@/components/team/InviteMemberDialog.vue";
import { useCapabilities } from "@/composables/useCapabilities";
import { useTeamInvitations } from "@/composables/useTeamInvitations";
import { useTeamRoles } from "@/composables/useTeamRoles";
import { formatDate } from "@/lib/format";
import { invitationStatusTheme } from "@/lib/status";
import type { InvitationRow } from "@/types/api";

const { invitations, loading, error, busy, reload, resend, revoke } = useTeamInvitations();
const { canManageMembers } = useCapabilities();
const { roleLabel } = useTeamRoles();

const query = ref(
	createListViewQuery({
		pageSize: 20,
		sort: { key: "creation", direction: "desc" },
	})
);
const inviteOpen = ref(false);

const filters: ListViewFilter[] = [
	{
		key: "status",
		label: "Status",
		options: ["Pending", "Accepted", "Expired", "Revoked", "Declined"].map((v) => ({
			label: v,
			value: v,
		})),
	},
];

const columns = computed<ListViewColumn<InvitationRow>[]>(() => [
	{
		accessorKey: "email",
		header: "Email",
		meta: { cellClass: "truncate font-medium" },
	},
	{
		id: "role",
		header: "Role",
		accessorFn: (i) => roleLabel(i.role),
		meta: { cellClass: "truncate" },
	},
	{
		accessorKey: "status",
		header: "Status",
		enableSorting: false,
		cell: ({ row }) =>
			h(Badge, {
				theme: invitationStatusTheme(row.original.status),
				label: row.original.status,
			}),
	},
	{
		id: "expires",
		header: "Expires",
		accessorFn: (i) => formatDate(i.expires_on) || "-",
	},
	{
		id: "actions",
		header: "",
		enableSorting: false,
		size: 1,
		meta: { align: "end" },
		cell: ({ row }) =>
			h(InvitationRowActions, {
				invitation: row.original,
				canManage: canManageMembers.value,
				busy: busy.value === row.original.name,
				onResend: resend,
				onRevoke: revoke,
			}),
	},
]);

function getInvitationKey(invitation: InvitationRow): string {
	return invitation.name;
}
</script>

<template>
	<div class="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
		<ListView
			v-model:query="query"
			:rows="invitations"
			:columns="columns"
			:row-key="getInvitationKey"
			:loading="loading"
			:error="error"
			:filters="filters"
			searchable
			search-placeholder="Search invitations..."
			item-label="invitation"
			:empty-state="{
				title: 'No invitations',
				description: 'Invitations you send to this team will appear here.',
			}"
			@retry="reload"
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

	<InviteMemberDialog v-model:open="inviteOpen" @invited="reload" />
</template>
