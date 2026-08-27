<script setup lang="ts">
import { Badge, Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import BillingGroupMembersDialog from '@/components/billing/BillingGroupMembersDialog.vue'
import BillingGroupRowActions from '@/components/billing/BillingGroupRowActions.vue'
import CreateBillingGroupDialog from '@/components/billing/CreateBillingGroupDialog.vue'
import RenameBillingGroupDialog from '@/components/billing/RenameBillingGroupDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBillingGroups } from '@/composables/useBillingGroups'
import { useCapabilities } from '@/composables/useCapabilities'
import { standingTheme } from '@/lib/status'
import type { BadgeTheme } from '@/lib/status'
import type { BillingGroup } from '@/types/billing'

// Billing Groups — a team's own partitions of its bill (ARCHITECTURE.md §2.1): a
// group's tagged subscriptions/cards/credits bill and settle on their own,
// separate from the team's consolidated one. Same "show a few, tray for the
// rest" shape as PayingForCard — only teams that use this (resellers billing
// several end-customers) need it, so it starts empty rather than demanding setup.
const VISIBLE = 5

defineEmits<{ open: [] }>()
const {
	groups,
	busy,
	pendingRename,
	pendingManageMembers,
	onToggle,
	onRename,
	onManageMembers,
	reloadGroups,
} = useBillingGroups()
const { canManageBilling } = useCapabilities()

const rows = computed(() => groups.data ?? [])
const visible = computed(() => rows.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, rows.value.length - VISIBLE))
const loading = computed(() => groups.loading && !groups.data)

const showCreate = ref(false)

// Only a disabled/off-standing group needs a badge — an enabled group with no
// billing trouble reads as the norm (mirrors PayingForRow's statusInfo).
function statusInfo(g: BillingGroup): { label: string; theme: BadgeTheme } | null {
	if (!g.enabled) return { label: 'Disabled', theme: 'gray' }
	if (g.standing && g.standing !== 'Current')
		return { label: g.standing, theme: standingTheme(g.standing) }
	return null
}

function subtitle(g: BillingGroup): string {
	return g.resource_count === 1 ? '1 resource' : `${g.resource_count} resources`
}
</script>

<template>
	<BillingCard
		title="Billing groups"
		title-info="Tag subscriptions, cards, and credits into a group to bill and settle them separately, apart from your consolidated invoice."
	>
		<template #action>
			<Button
				v-if="canManageBilling"
				variant="ghost"
				size="xs"
				icon="lucide-plus"
				aria-label="Create billing group"
				@click="showCreate = true"
			/>
		</template>

		<div v-if="loading" class="space-y-3 py-1">
			<div v-for="i in 2" :key="i" class="flex items-center gap-3">
				<span
					class="size-4 shrink-0 animate-pulse rounded-4 bg-surface-gray-2"
				/>
				<div class="flex-1 space-y-1.5">
					<span
						class="block h-3.5 w-40 animate-pulse rounded-4 bg-surface-gray-2"
					/>
					<span
						class="block h-3 w-24 animate-pulse rounded-4 bg-surface-gray-2"
					/>
				</div>
			</div>
		</div>

		<template v-else-if="rows.length">
			<div class="divide-y divide-outline-gray-1">
				<div
					v-for="g in visible"
					:key="g.name"
					class="flex items-center justify-between gap-3 py-3"
				>
					<div class="flex min-w-0 items-start gap-2.5">
						<span
							class="lucide-layers mt-0.5 size-4 shrink-0 text-ink-gray-5"
							aria-hidden="true"
						/>
						<div class="min-w-0">
							<div class="flex items-center gap-2">
								<span class="truncate text-sm-medium text-ink-gray-9">
									{{ g.title }}
								</span>
								<Badge
									v-if="statusInfo(g)"
									:theme="statusInfo(g)!.theme"
									:label="statusInfo(g)!.label"
								/>
							</div>
							<div class="truncate text-p-sm text-ink-gray-5">
								{{ subtitle(g) }}
							</div>
						</div>
					</div>
					<BillingGroupRowActions
						:group="g"
						:can-manage="canManageBilling"
						:busy="busy === g.name"
						@rename="onRename"
						@toggle="onToggle"
						@manage-members="onManageMembers"
					/>
				</div>
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
			icon="lucide-layers"
			title="No billing groups yet"
			description="Create a group to bill some of your subscriptions separately — e.g. one invoice per end-customer you resell to."
		>
			<template v-if="canManageBilling" #action>
				<Button
					variant="solid"
					theme="gray"
					label="Create billing group"
					@click="showCreate = true"
				>
					<template #prefix
						><span class="lucide-plus size-4" aria-hidden="true" /></template
					>
				</Button>
			</template>
		</EmptyState>

		<CreateBillingGroupDialog v-model="showCreate" @created="reloadGroups" />
		<RenameBillingGroupDialog v-model:group="pendingRename" @renamed="reloadGroups" />
		<BillingGroupMembersDialog
			v-model:group="pendingManageMembers"
			@changed="reloadGroups"
		/>
	</BillingCard>
</template>
