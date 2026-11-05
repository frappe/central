<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useSession } from '@/composables/useSession'
import { useSupport } from '@/composables/useSupport'

const { activeTeamLabel } = useSession()
const { getTicketUrl } = useSupport()
const ticketUrl = computed(() => getTicketUrl({ Team: activeTeamLabel.value }))
</script>

<template>
	<div class="p-6">
		<EmptyState
			icon="lucide-circle-pause"
			:title="`${activeTeamLabel} is suspended`"
			description="Frappe Cloud support suspended this team, so its members cannot open it. Its data is kept. Switch to another team, or contact support to find out why."
		>
			<template #action>
				<Button
					v-if="ticketUrl"
					label="Contact support"
					:href="ticketUrl"
					icon-right="lucide-external-link"
				/>
			</template>
		</EmptyState>
	</div>
</template>
