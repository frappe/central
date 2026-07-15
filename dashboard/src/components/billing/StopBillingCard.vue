<script setup lang="ts">
import { Button } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useCapabilities } from '@/composables/useCapabilities'

// Stop billing — suspend all of the team's servers.
//
// GROUNDING GAP (#69): there is no backend endpoint for this yet. The control is
// rendered disabled until one lands (e.g. a suspend-all action gated on
// billing:manage). Wiring it up is intentionally deferred — see the issue note.
const { canManageBilling } = useCapabilities()
</script>

<template>
	<BillingCard title="Stop billing">
		<div
			class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
		>
			<p class="text-p-sm text-ink-gray-5">
				Suspend every server on this team to pause charges. Sites go offline;
				nothing is deleted. This action isn't available yet — the backend
				endpoint is pending.
			</p>
			<Button
				v-if="canManageBilling"
				variant="subtle"
				theme="red"
				label="Stop billing"
				:disabled="true"
				class="shrink-0"
			/>
		</div>
	</BillingCard>
</template>
