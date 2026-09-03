<script setup lang="ts">
import { Badge, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import ProjectRowActions from '@/components/billing/ProjectRowActions.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useProjects } from '@/composables/useProjects'
import { money } from '@/lib/format'
import { standingTheme } from '@/lib/status'
import type { BadgeTheme } from '@/lib/status'
import type { Project } from '@/types/billing'

// Every Project, in full. The card keeps the top few; this is where the long
// tail goes, so the card never grows its own scrollbar.
const open = defineModel<boolean>('open', { default: false })
const { canManageBilling } = useCapabilities()
const { projects, busy, onToggle, onRename, onManageMembers } = useProjects()
const { currency } = useBillingOverview()

const rows = computed(() => projects.data ?? [])
const loading = computed(() => projects.loading && !projects.data)

const subtitle = computed(() =>
	rows.value.length
		? `${rows.value.length} project${rows.value.length === 1 ? '' : 's'}`
		: undefined,
)

function statusInfo(p: Project): { label: string; theme: BadgeTheme } | null {
	if (!p.enabled) return { label: 'Disabled', theme: 'gray' }
	if (p.standing && p.standing !== 'Current')
		return { label: p.standing, theme: standingTheme(p.standing) }
	return null
}

function rowSubtitle(p: Project): string {
	const resources = p.resource_count === 1 ? '1 resource' : `${p.resource_count} resources`
	if (!p.spending_limit) return resources
	return `${resources} · ${money(p.committed_run_rate, currency.value)} of ${money(p.spending_limit, currency.value)}/mo`
}
</script>

<template>
	<SidePanel v-model:open="open" title="Projects" :subtitle="subtitle">
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>
		<div v-else class="divide-y divide-outline-gray-1 px-4">
			<div
				v-for="p in rows"
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
							{{ rowSubtitle(p) }}
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
	</SidePanel>
</template>
