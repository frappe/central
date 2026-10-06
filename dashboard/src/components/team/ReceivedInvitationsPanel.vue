<script setup lang="ts">
import { Avatar, Button, Skeleton } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'
import { useMyInvitations } from '@/composables/useMyInvitations'
import { formatDate } from '@/lib/format'

// The signed-in user's pending invitations across teams.
// Accepting joins the team and switches to it; declining clears the invite.
const { invitations, loading, busy, accept, decline } = useMyInvitations()
</script>

<template>
	<div class="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
		<div v-if="loading" class="mx-auto max-w-2xl space-y-3">
			<Skeleton v-for="n in 2" :key="n" class="h-24 rounded-6" />
		</div>

		<EmptyState
			v-else-if="!invitations.length"
			title="No invitations"
			description="Invitations sent to you will appear here."
		/>

		<div v-else class="mx-auto max-w-2xl space-y-4">
			<article
				v-for="invite in invitations"
				:key="invite.name"
				class="rounded-6 border border-outline-gray-2 bg-surface-elevation-1 p-5"
			>
				<div class="flex items-start gap-3">
					<Avatar :label="invite.team_name" size="xl" shape="square" />
					<div class="min-w-0 flex-1">
						<h2 class="truncate text-base font-semibold text-ink-gray-9">
							{{ invite.team_name }}
						</h2>
						<p class="mt-0.5 text-p-sm text-ink-gray-5">
							Invited as
							<span class="font-medium text-ink-gray-7">{{ invite.role }}</span>
							<template v-if="invite.invited_by">
								by {{ invite.invited_by }}</template
							>
						</p>
						<p v-if="invite.expires_on" class="mt-1 text-xs text-ink-gray-5">
							Expires {{ formatDate(invite.expires_on) }}
						</p>
					</div>
				</div>
				<div class="mt-4 flex items-center gap-2">
					<Button
						variant="solid"
						label="Accept & join"
						:loading="busy === invite.name"
						@click="accept(invite)"
					/>
					<Button
						label="Decline"
						:loading="busy === invite.name"
						@click="decline(invite)"
					/>
				</div>
			</article>
		</div>
	</div>
</template>
