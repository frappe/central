<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import BillingCard from '@/components/billing/BillingCard.vue'
import PayingForRow from '@/components/billing/PayingForRow.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayingFor } from '@/composables/usePayingFor'

const VISIBLE = 5

defineEmits<{ open: [] }>()
const router = useRouter()
const { canManageBilling } = useCapabilities()
const { rows, loading, currency, openServer } = usePayingFor()

const visible = computed(() => rows.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, rows.value.length - VISIBLE))

function goToAddons(): void {
	router.push({ name: 'Addons' })
}
</script>

<template>
	<BillingCard title="Subscriptions">
		<div v-if="loading" class="space-y-3 py-1">
			<div v-for="i in 3" :key="i" class="flex items-center gap-3">
				<span
					class="size-4 shrink-0 animate-pulse rounded-4 bg-surface-gray-2"
				/>
				<div class="flex-1 space-y-1.5">
					<span
						class="block h-3.5 w-40 animate-pulse rounded-4 bg-surface-gray-2"
					/>
					<span
						class="block h-3 w-28 animate-pulse rounded-4 bg-surface-gray-2"
					/>
				</div>
			</div>
		</div>

		<template v-else-if="rows.length">
			<div class="divide-y divide-outline-gray-1">
				<PayingForRow
					v-for="row in visible"
					:key="row.id"
					:row="row"
					:currency="currency"
					@open="openServer"
				/>
			</div>
			<Button
				v-if="hidden"
				variant="ghost"
				size="sm"
				class="-mb-2 -ml-2 mt-2"
				:label="`View all ${rows.length}`"
				@click="$emit('open')"
			>
				<template #suffix>
					<span class="lucide-chevron-right size-4" aria-hidden="true" />
				</template>
			</Button>
		</template>

		<EmptyState
			v-else
			icon="lucide-server"
			title="Nothing being billed"
			description="Servers and metered services you're subscribed to will show here with what they cost."
		>
			<template v-if="canManageBilling" #action>
				<Button variant="subtle" label="Browse add-ons" @click="goToAddons" />
			</template>
		</EmptyState>
	</BillingCard>
</template>
