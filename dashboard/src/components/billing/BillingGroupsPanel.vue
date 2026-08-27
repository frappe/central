<script setup lang="ts">
import { Badge, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import BillingGroupRowActions from '@/components/billing/BillingGroupRowActions.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useBillingGroups } from '@/composables/useBillingGroups'
import { useCapabilities } from '@/composables/useCapabilities'
import { standingTheme } from '@/lib/status'
import type { BadgeTheme } from '@/lib/status'
import type { BillingGroup } from '@/types/billing'

// Every Billing Group, in full. The card keeps the top few; this is where the
// long tail goes, so the card never grows its own scrollbar.
const open = defineModel<boolean>('open', { default: false })
const { canManageBilling } = useCapabilities()
const { groups, busy, onToggle, onRename, onManageMembers } = useBillingGroups()

const rows = computed(() => groups.data ?? [])
const loading = computed(() => groups.loading && !groups.data)

const subtitle = computed(() =>
	rows.value.length
		? `${rows.value.length} group${rows.value.length === 1 ? '' : 's'}`
		: undefined,
)

function statusInfo(g: BillingGroup): { label: string; theme: BadgeTheme } | null {
	if (!g.enabled) return { label: 'Disabled', theme: 'gray' }
	if (g.standing && g.standing !== 'Current')
		return { label: g.standing, theme: standingTheme(g.standing) }
	return null
}

function rowSubtitle(g: BillingGroup): string {
	return g.resource_count === 1 ? '1 resource' : `${g.resource_count} resources`
}
</script>

<template>
	<SidePanel v-model:open="open" title="Billing groups" :subtitle="subtitle">
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>
		<div v-else class="divide-y divide-outline-gray-1 px-4">
			<div
				v-for="g in rows"
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
							{{ rowSubtitle(g) }}
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
	</SidePanel>
</template>
