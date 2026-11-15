<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed } from 'vue'
import { useSession } from '@/composables/useSession'
import { __ } from '@/lib/translate'

// While a partner pays for the team, the team gets no invoice of its own for its usage.
const session = useSession()
const paidBy = computed(
	() =>
		session.teams.value.find((team) => team.name === session.activeTeam.value)
			?.paid_by ?? null,
)
</script>

<template>
	<Alert
		v-if="paidBy"
		theme="blue"
		:title="__('Paid by {0}', [paidBy])"
		:description="
			__(
				'{0} pays for your usage on its monthly invoice, in its currency. Your prices show in that currency.',
				[paidBy],
			)
		"
	/>
</template>
