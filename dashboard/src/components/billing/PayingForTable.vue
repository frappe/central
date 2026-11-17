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
	rounded?: boolean
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

const serverPlan = (
	sub: SubscriptionRow,
): { name: string; details: string } => {
	const [name = '', ...specs] = (sub.plan_title ?? '').split(/\s+[—–]\s+/)

	if (name === subscriptionTitle(sub))
		return { name: '', details: sub.region || sub.billing_cycle }

	return {
		name,
		details:
			[...specs, sub.region].filter(Boolean).join(' · ') || sub.billing_cycle,
	}
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

const overAllowance = (s: ServiceRow): boolean =>
	s.allowance > 0 && s.period_usage > s.allowance
</script>

<template>
	<Table
		:flush="!rounded"
		:columns="columns"
		:rows="rows"
		:hide-header="hideHeader"
	>
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
				<span class="text-ink-gray-7">{{ serverPlan(row.sub).name }}</span>
				<template v-if="serverPlan(row.sub).name"> · </template>
				{{ serverPlan(row.sub).details }}
			</span>

			<span v-else-if="row.kind === 'service'" class="text-sm text-ink-gray-5">
				{{ usageLabel(row.service) }}
			</span>
		</template>

		<template #cost="{ row }">
			<div v-if="row.kind === 'server'" class="flex flex-col gap-0.5">
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
			</div>

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
