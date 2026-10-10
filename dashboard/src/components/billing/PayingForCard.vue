<script setup lang="ts">
import { Button, Skeleton } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import AssignProjectDialog from '@/components/billing/AssignProjectDialog.vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import PayingForRow from '@/components/billing/PayingForRow.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayingFor } from '@/composables/usePayingFor'
import { subscriptionTitle } from '@/lib/subscriptions'

const VISIBLE = 5

defineEmits<{ open: [] }>()
const router = useRouter()
const { canManageBilling } = useCapabilities()
const {
	rows,
	loading,
	currency,
	busy,
	pendingPause,
	pendingAssignProject,
	openServer,
	askPause,
	confirmPause,
	onResume,
	askAssignProject,
	onAssignedProject,
} = usePayingFor()

const visible = computed(() => rows.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, rows.value.length - VISIBLE))

function goToObjectStorage(): void {
	router.push({ name: 'ObjectStorage' })
}
</script>

<template>
	<BillingCard title="Subscriptions">
		<div v-if="loading" class="space-y-3 py-1">
			<div v-for="i in 3" :key="i" class="flex items-center gap-3">
				<Skeleton class="size-4 shrink-0 rounded-4" />
				<div class="flex-1 space-y-1.5">
					<Skeleton class="h-3.5 w-40 rounded-4" />
					<Skeleton class="h-3 w-28 rounded-4" />
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
					:can-manage="canManageBilling"
					:busy="busy"
					@open="openServer"
					@pause="askPause"
					@resume="onResume"
					@assign-project="askAssignProject"
				/>
			</div>
			<Button
				v-if="hidden"
				variant="ghost"
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
				<Button label="Open Object Storage" @click="goToObjectStorage" />
			</template>
		</EmptyState>

		<ConfirmDialog
			v-model:target="pendingPause"
			title="Pause billing"
			:message="`Pause billing for ${pendingPause ? subscriptionTitle(pendingPause) : ''}? This stops the server/VM and the site(s)/services running on it, and stops charges until you resume.`"
			confirm-label="Pause billing"
			:loading="busy === pendingPause?.name"
			@confirm="confirmPause"
		/>
		<AssignProjectDialog
			v-model:subscription="pendingAssignProject"
			@assigned="onAssignedProject"
		/>
	</BillingCard>
</template>
