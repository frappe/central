<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import { useSession } from '@/composables/useSession'
import { __ } from '@/lib/translate'

// Partner staff work in a customer's team without being its members, so the console says whose
// team this is and how to go back.
const session = useSession()
const team = computed(() =>
	session.teams.value.find(
		(option) => option.name === session.activeTeam.value && option.via_partner,
	),
)

function goBack(): void {
	if (team.value?.via_partner_team)
		session.setActiveTeam(team.value.via_partner_team, '/dashboard/customers')
}
</script>

<template>
	<div
		v-if="team"
		role="status"
		class="flex shrink-0 items-center justify-between gap-3 border-b border-outline-gray-2 bg-surface-gray-2 px-4 py-1.5"
	>
		<p class="min-w-0 truncate text-p-sm text-ink-gray-8">
			{{ __('You are working in {0} for {1} with {2} access.', [
					team.label,
					team.via_partner,
					team.role,
				]) }}
		</p>
		<Button
			size="sm"
			:label="__('Back to {0}', [team.via_partner])"
			@click="goBack"
		/>
	</div>
</template>
