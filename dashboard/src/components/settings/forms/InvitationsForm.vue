<script setup lang="ts">
import { Avatar, Badge, Button, Skeleton } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'
import { useMyInvitations } from '@/composables/useMyInvitations'
import { formatDate } from '@/lib/format'

// Invitations addressed to you. Accepting joins the team and switches to it.
const { invitations, loading, error, busy, reload, accept, decline } =
	useMyInvitations()
</script>

<template>
	<div class="pt-6">
		<EmptyState
			v-if="error"
			icon="lucide-cloud-off"
			title="Invitations couldn't load"
			:description="error"
		>
			<template #action>
				<Button label="Retry" @click="reload" />
			</template>
		</EmptyState>

		<div v-else-if="loading && !invitations.length" class="space-y-2">
			<Skeleton v-for="n in 2" :key="n" class="h-16 rounded-6" />
		</div>

		<EmptyState
			v-else-if="!invitations.length"
			icon="lucide-mail-check"
			title="No pending invitations"
			description="When a team invites you, the invitation shows here."
		/>

		<ul v-else class="divide-y divide-outline-gray-1 rounded-6 border">
			<li
				v-for="invite in invitations"
				:key="invite.name"
				class="flex items-center gap-3 px-4 py-3"
			>
				<Avatar :label="invite.team_name" size="lg" shape="square" />
				<div class="min-w-0 flex-1">
					<p class="flex items-center gap-2 text-base-medium text-ink-gray-8">
						<span class="truncate">{{ invite.team_name }}</span>
						<Badge :label="invite.role_name" />
					</p>
					<p class="truncate text-p-sm text-ink-gray-5">
						<template v-if="invite.invited_by"
							>Invited by {{ invite.invited_by }}</template
						>
						<template v-if="invite.invited_by && invite.expires_on">
							·
						</template>
						<template v-if="invite.expires_on"
							>Expires {{ formatDate(invite.expires_on) }}</template
						>
					</p>
				</div>
				<Button
					label="Decline"
					:disabled="!!busy"
					:loading="busy === invite.name"
					@click="decline(invite)"
				/>
				<Button
					variant="solid"
					label="Accept"
					:disabled="!!busy"
					:loading="busy === invite.name"
					@click="accept(invite)"
				/>
			</li>
		</ul>
	</div>
</template>
