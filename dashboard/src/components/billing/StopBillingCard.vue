<script setup lang="ts">
import { Button } from 'frappe-ui'
import { useCapabilities } from '@/composables/useCapabilities'

// Suspend all servers — the team's kill switch for spend. Named for what it
// does, not for what it saves: "stop billing" reads like closing the account,
// when the actual effect is every server powering down. A bare section, not a
// card: it's a quiet footer verb under the card stack, not a data surface.
//
// GROUNDING GAP (#69): there is no backend endpoint for this yet. The control is
// rendered disabled until one lands (e.g. a suspend-all action gated on
// billing:manage). Wiring it up is intentionally deferred — see the issue note.
const { canManageBilling } = useCapabilities()
</script>

<template>
	<section class="flex items-start justify-between gap-4 px-5">
		<div class="min-w-0">
			<h2 class="text-base-medium text-ink-gray-8">Suspend all servers</h2>
			<p class="mt-0.5 text-p-sm text-ink-gray-5">
				Powers down every server on this team so charges stop accruing. Sites go
				offline; nothing is deleted, and you can start them again any time.
			</p>
		</div>
		<Button
			v-if="canManageBilling"
			variant="subtle"
			theme="red"
			label="Suspend all"
			:disabled="true"
			title="Suspend all servers — coming soon"
			class="shrink-0"
		/>
	</section>
</template>
