<script setup lang="ts">
import { Badge, Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import CreateProjectDialog from '@/components/billing/CreateProjectDialog.vue'
import ProjectMembersDialog from '@/components/billing/ProjectMembersDialog.vue'
import ProjectRowActions from '@/components/billing/ProjectRowActions.vue'
import RenameProjectDialog from '@/components/billing/RenameProjectDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useProjects } from '@/composables/useProjects'
import { money } from '@/lib/format'
import { standingTheme } from '@/lib/status'
import type { BadgeTheme } from '@/lib/status'
import type { Project } from '@/types/billing'

// Projects — a team's own cost-breakdown tags: subscriptions tagged into the
// same project show grouped under it on the invoice/forecast line items, and a
// project can cap its own committed monthly run-rate (spending_limit). Every
// team still gets exactly one consolidated invoice — a Project changes nothing
// about how or when anything is billed. Same "show a few, tray for the rest"
// shape as PayingForCard — only teams that use this need it, so it starts empty
// rather than demanding setup.
const VISIBLE = 5

defineEmits<{ open: [] }>()
const {
	projects,
	busy,
	pendingRename,
	pendingManageMembers,
	onToggle,
	onRename,
	onManageMembers,
	reloadProjects,
} = useProjects()
const { canManageBilling } = useCapabilities()
const { currency } = useBillingOverview()

const rows = computed(() => projects.data ?? [])
const visible = computed(() => rows.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, rows.value.length - VISIBLE))
const loading = computed(() => projects.loading && !projects.data)

const showCreate = ref(false)

// Only a disabled/off-standing project needs a badge — an enabled project with
// no billing trouble reads as the norm (mirrors PayingForRow's statusInfo).
function statusInfo(p: Project): { label: string; theme: BadgeTheme } | null {
	if (!p.enabled) return { label: 'Disabled', theme: 'gray' }
	if (p.standing && p.standing !== 'Current')
		return { label: p.standing, theme: standingTheme(p.standing) }
	return null
}

function subtitle(p: Project): string {
	const resources = p.resource_count === 1 ? '1 resource' : `${p.resource_count} resources`
	if (!p.spending_limit) return resources
	return `${resources} · ${money(p.committed_run_rate, currency.value)} of ${money(p.spending_limit, currency.value)}/mo`
}
</script>

<template>
	<BillingCard
		title="Projects"
		title-info="Tag subscriptions into a project to see their cost grouped separately in your invoice breakdown, and optionally cap how much can be tagged into it."
	>
		<template #action>
			<Button
				v-if="canManageBilling"
				variant="ghost"
				size="xs"
				icon="lucide-plus"
				aria-label="Create project"
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
					v-for="p in visible"
					:key="p.name"
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
									{{ p.title }}
								</span>
								<Badge
									v-if="statusInfo(p)"
									:theme="statusInfo(p)!.theme"
									:label="statusInfo(p)!.label"
								/>
							</div>
							<div class="truncate text-p-sm text-ink-gray-5">
								{{ subtitle(p) }}
							</div>
						</div>
					</div>
					<ProjectRowActions
						:project="p"
						:can-manage="canManageBilling"
						:busy="busy === p.name"
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
			title="No projects yet"
			description="Create a project to see the cost of a group of subscriptions broken out separately on your invoice — e.g. one per end-customer or environment."
		>
			<template v-if="canManageBilling" #action>
				<Button
					variant="solid"
					theme="gray"
					label="Create project"
					@click="showCreate = true"
				>
					<template #prefix
						><span class="lucide-plus size-4" aria-hidden="true" /></template
					>
				</Button>
			</template>
		</EmptyState>

		<CreateProjectDialog v-model="showCreate" @created="reloadProjects" />
		<RenameProjectDialog v-model:project="pendingRename" @saved="reloadProjects" />
		<ProjectMembersDialog
			v-model:project="pendingManageMembers"
			@changed="reloadProjects"
		/>
	</BillingCard>
</template>
