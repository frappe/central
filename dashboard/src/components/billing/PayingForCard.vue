<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import AssignBillingGroupDialog from '@/components/billing/AssignBillingGroupDialog.vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import PayingForRow from '@/components/billing/PayingForRow.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayingFor } from '@/composables/usePayingFor'
import { money } from '@/lib/format'

// What you're paying for — servers and team-level metered services in one list,
// each row carrying what it has cost so far this cycle.
//
// The card shows the biggest few and hands the rest to a tray. An overview that
// scrolls internally stops being an overview: the page already scrolls, and a
// second scrollbar inside a card hides rows behind a gesture nobody makes. Five
// is enough to show the shape of the spend; the tray is where you go to read all
// of it.
const VISIBLE = 5

defineEmits<{ open: [] }>()
const router = useRouter()
const { canManageBilling } = useCapabilities()
const {
	rows,
	loading,
	currency,
	total,
	busy,
	pendingPause,
	pendingAssignGroup,
	openServer,
	askPause,
	confirmPause,
	onResume,
	askAssignGroup,
	onAssignedGroup,
} = usePayingFor()

const visible = computed(() => rows.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, rows.value.length - VISIBLE))

function serverTitle(sub: {
	server: string | null
	plan_title: string | null
	name: string
}): string {
	return sub.server || sub.plan_title || sub.name
}
function goToAddons(): void {
	router.push({ name: 'Addons' })
}
</script>

<template>
	<BillingCard
		title="What you're paying for"
		:description="total > 0 ? `${money(total, currency)} so far this cycle` : undefined"
	>
		<template v-if="canManageBilling" #action>
			<Button
				variant="ghost"
				size="xs"
				icon="lucide-plus"
				title="Browse add-ons"
				label="Add-ons"
				@click="goToAddons"
			/>
		</template>

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
					:can-manage="canManageBilling"
					:busy="busy"
					@open="openServer"
					@pause="askPause"
					@resume="onResume"
					@assign-group="askAssignGroup"
				/>
			</div>
			<Button
				v-if="hidden"
				variant="ghost"
				size="sm"
				class="-ml-2 mt-2"
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

		<ConfirmDialog
			v-model:target="pendingPause"
			title="Pause billing"
			:message="`Pause billing for ${pendingPause ? serverTitle(pendingPause) : ''}? This stops the server/VM and the site(s)/services running on it, and stops charges until you resume.`"
			confirm-label="Pause billing"
			:loading="busy === pendingPause?.name"
			@confirm="confirmPause"
		/>
		<AssignBillingGroupDialog
			v-model:subscription="pendingAssignGroup"
			@assigned="onAssignedGroup"
		/>
	</BillingCard>
</template>
