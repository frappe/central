<script setup lang="ts">
import { Button } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'
import { useSession } from '@/composables/useSession'
import { useSupport } from '@/composables/useSupport'

const { activeTeamLabel } = useSession()
const { hasSupport, openSupport } = useSupport()
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
					v-if="hasSupport"
					label="Contact support"
					icon-left="lucide-life-buoy"
					@click="openSupport({ Team: activeTeamLabel })"
				/>
			</template>
		</EmptyState>
	</div>
</template>
