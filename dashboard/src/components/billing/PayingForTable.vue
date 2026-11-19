<script setup lang="ts">
import { Badge } from 'frappe-ui'
import SubscriptionRowActions from '@/components/billing/SubscriptionRowActions.vue'
import Table from '@/components/common/Table.vue'
import { money } from '@/lib/format'
import { subscriptionTitle } from '@/lib/subscriptions'

import type {
	PayingForItem,
	ServiceRow,
	SubscriptionRow,
} from '@/types/billing'

defineProps<{
	rows: PayingForItem[]
	currency: string
	canManage: boolean
	busy: string
	hideHeader?: boolean
}>()

defineEmits<{
	open: [sub: SubscriptionRow]
	pause: [sub: SubscriptionRow]
	resume: [sub: SubscriptionRow]
	assignProject: [sub: SubscriptionRow]
}>()

const columns = [
	{ key: 'name', label: 'Name' },
	{ key: 'usage', label: 'Usage', class: 'w-2/5' },
	{ key: 'cost', label: 'Cost' },
	{ key: 'actions', label: '' },
]

type BadgeTheme = 'gray' | 'red' | 'blue' | 'green' | 'amber' | 'violet'

const serverSubtitle = (sub: SubscriptionRow): string => {
	const parts: string[] = []

	if (sub.plan_title && sub.plan_title !== subscriptionTitle(sub))
		parts.push(sub.plan_title)

	if (sub.region) parts.push(sub.region)

	return parts.join(' · ') || sub.billing_cycle || 'Monthly'
}

const statusInfo = (
	sub: SubscriptionRow,
): { label: string; theme: BadgeTheme } | null => {
	if (sub.status === 'Terminated') return { label: 'Terminated', theme: 'red' }

	if (sub.account_standing === 'Suspended')
		return { label: 'Suspended', theme: 'amber' }

	if (!sub.enabled) return { label: 'Paused', theme: 'gray' }

	if (sub.status === 'Stopped') return { label: 'Stopped', theme: 'gray' }

	return null
}

const isTerminated = (sub: SubscriptionRow): boolean =>
	sub.status === 'Terminated'

const showRate = (row: {
	cost: number | null
	sub: SubscriptionRow
}): boolean => {
	if (row.sub.monthly_rate == null || isTerminated(row.sub)) return false

	if (row.cost == null) return true

	return Math.abs(row.sub.monthly_rate - row.cost) >= 0.005
}

const serviceIcon = (s: ServiceRow): string => {
	const key = `${s.resource_type || ''} ${s.title || ''}`.toLowerCase()

	if (/token|ai/.test(key)) return 'lucide-sparkles'

	if (/pdf|print/.test(key)) return 'lucide-file-text'

	if (/mail/.test(key)) return 'lucide-mail'

	if (/storage|object/.test(key)) return 'lucide-archive'

	return 'lucide-gauge'
}

const usageLabel = (s: ServiceRow): string => {
	const unit = s.unit || 'units'

	if (s.settlement_mode === 'Prepaid Pack' && s.allowance) {
		const remaining = Math.max(0, s.allowance - s.period_usage)

		return `${remaining.toLocaleString()} / ${s.allowance.toLocaleString()} ${unit} left`
	}

	const included = s.allowance
		? ` of ${s.allowance.toLocaleString()} incl.`
		: ''

	return `${s.period_usage.toLocaleString()} ${unit}${included}`
}

const exhausted = (s: ServiceRow): boolean =>
	s.settlement_mode === 'Prepaid Pack' &&
	s.allowance > 0 &&
	s.period_usage >= s.allowance

const usagePct = (s: ServiceRow): number => {
	if (!s.allowance) return 0

	return Math.min(100, Math.round((s.period_usage / s.allowance) * 100))
}

const overAllowance = (s: ServiceRow): boolean =>
	s.allowance > 0 && s.period_usage > s.allowance
</script>

<template>
	<Table flush :columns="columns" :rows="rows" :hide-header="hideHeader">
		<template #name="{ row }">
			<component
				:is="row.sub.gateway_url ? 'button' : 'div'"
				v-if="row.kind === 'server'"
				class="group flex min-w-0 items-center gap-2.5 text-left"
				@click="$emit('open', row.sub)"
			>
				<span
					class="lucide-server size-4 shrink-0 text-ink-gray-5"
					aria-hidden="true"
				/>
				<span
					class="truncate text-base text-ink-gray-9"
					:class="row.sub.gateway_url ? 'transition-colors group-hover:text-ink-gray-7' : ''"
				>
					{{ subscriptionTitle(row.sub) }}
				</span>
				<Badge
					v-if="statusInfo(row.sub)"
					:theme="statusInfo(row.sub)!.theme"
					:label="statusInfo(row.sub)!.label"
				/>
			</component>

			<div v-else class="flex min-w-0 items-center gap-2.5">
				<span
					class="size-4 shrink-0 text-ink-gray-5"
					:class="serviceIcon(row.service)"
					aria-hidden="true"
				/>
				<span class="truncate text-base text-ink-gray-9">
					{{ row.service.title || row.service.plan }}
				</span>
				<Badge
					v-if="row.service.settlement_mode !== 'Prepaid Pack'"
					label="Metered"
				/>
				<Badge v-if="exhausted(row.service)" theme="amber" label="Exhausted" />
				<Badge
					v-else-if="overAllowance(row.service)"
					theme="amber"
					label="Over"
				/>
			</div>
		</template>

		<template #usage="{ row }">
			<span v-if="row.kind === 'server'" class="text-sm text-ink-gray-5">
				{{ serverSubtitle(row.sub) }}
			</span>

			<div v-else-if="row.kind === 'service'" class="flex items-center gap-2.5">
				<div
					v-if="row.service.allowance > 0"
					class="h-1 flex-1 overflow-hidden rounded-1 bg-surface-gray-2"
				>
					<span
						class="block h-full"
						:class="overAllowance(row.service) ? 'bg-surface-amber-5' : 'bg-surface-gray-7'"
						:style="{ width: `${overAllowance(row.service) ? 100 : usagePct(row.service)}%` }"
					/>
				</div>
				<span class="text-sm tabular-nums text-ink-gray-5">
					{{ usageLabel(row.service) }}
				</span>
			</div>
		</template>

		<template #cost="{ row }">
			<template v-if="row.kind === 'server'">
				<span
					class="block text-base tabular-nums"
					:class="isTerminated(row.sub) ? 'text-ink-gray-4' : 'text-ink-gray-9'"
				>
					{{ row.cost != null ? money(row.cost, currency) : '—' }}
				</span>
				<span
					v-if="showRate(row)"
					class="block text-sm tabular-nums text-ink-gray-5"
				>
					{{ money(row.sub.monthly_rate, currency, { trimTrailingZeros: true }) }}/mo
				</span>
			</template>

			<span v-else class="text-base tabular-nums text-ink-gray-9">
				{{ money(row.cost ?? 0, currency) }}
			</span>
		</template>

		<template #actions="{ row }">
			<SubscriptionRowActions
				v-if="row.kind === 'server'"
				:subscription="row.sub"
				:can-manage="canManage"
				:busy="busy === row.sub.name"
				@open="$emit('open', $event)"
				@pause="$emit('pause', $event)"
				@resume="$emit('resume', $event)"
				@assign-project="$emit('assignProject', $event)"
			/>
		</template>
	</Table>
</template>
