<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { money } from '@/lib/format'
import type {
	PayingForItem,
	ServiceRow,
	SubscriptionRow,
} from '@/types/billing'

defineProps<{
	row: PayingForItem
	currency: string
}>()
defineEmits<{
	open: [sub: SubscriptionRow]
<<<<<<< HEAD
	pause: [sub: SubscriptionRow]
	resume: [sub: SubscriptionRow]
	assignProject: [sub: SubscriptionRow]
=======
>>>>>>> develop
}>()

type BadgeTheme = 'gray' | 'red' | 'blue' | 'green' | 'amber' | 'violet'

function serverTitle(sub: SubscriptionRow): string {
	return sub.server || sub.plan_title || sub.name
}
function serverSubtitle(sub: SubscriptionRow): string {
	const parts: string[] = []
	if (sub.plan_title && sub.plan_title !== serverTitle(sub))
		parts.push(sub.plan_title)
	if (sub.region) parts.push(sub.region)
	return parts.join(' · ') || sub.billing_cycle || 'Monthly'
}
function statusInfo(
	sub: SubscriptionRow,
): { label: string; theme: BadgeTheme } | null {
	if (sub.status === 'Terminated') return { label: 'Terminated', theme: 'red' }
	if (sub.account_standing === 'Suspended')
		return { label: 'Suspended', theme: 'amber' }
	if (!sub.enabled) return { label: 'Paused', theme: 'gray' }
	if (sub.status === 'Stopped') return { label: 'Stopped', theme: 'gray' }
	return null
}
const isTerminated = (sub: SubscriptionRow): boolean =>
	sub.status === 'Terminated'

function showRate(row: { cost: number | null; sub: SubscriptionRow }): boolean {
	if (row.sub.monthly_rate == null || isTerminated(row.sub)) return false
	if (row.cost == null) return true
	return Math.abs(row.sub.monthly_rate - row.cost) >= 0.005
}

function serviceIcon(s: ServiceRow): string {
	const key = `${s.resource_type || ''} ${s.title || ''}`.toLowerCase()
	if (/token|ai/.test(key)) return 'lucide-sparkles'
	if (/pdf|print/.test(key)) return 'lucide-file-text'
	if (/mail/.test(key)) return 'lucide-mail'
	if (/storage|object/.test(key)) return 'lucide-archive'
	return 'lucide-gauge'
}
function usageLabel(s: ServiceRow): string {
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
function exhausted(s: ServiceRow): boolean {
	return (
		s.settlement_mode === 'Prepaid Pack' &&
		s.allowance > 0 &&
		s.period_usage >= s.allowance
	)
}
function usagePct(s: ServiceRow): number {
	if (!s.allowance) return 0
	return Math.min(100, Math.round((s.period_usage / s.allowance) * 100))
}
function overAllowance(s: ServiceRow): boolean {
	return s.allowance > 0 && s.period_usage > s.allowance
}
</script>

<template>
	<div class="flex items-center justify-between gap-3 py-3">
		<!-- Server -->
		<template v-if="row.kind === 'server'">
			<component
				:is="row.sub.gateway_url ? 'button' : 'div'"
				class="group min-w-0 text-left"
				@click="$emit('open', row.sub)"
			>
				<div class="flex items-center gap-2">
					<span
						class="lucide-server mt-0.5 size-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					<span
						class="truncate text-base-medium text-ink-gray-9"
						:class="row.sub.gateway_url ? 'transition-colors group-hover:text-ink-gray-7' : ''"
					>
						{{ serverTitle(row.sub) }}
					</span>
					<Badge
						v-if="statusInfo(row.sub)"
						:theme="statusInfo(row.sub)!.theme"
						:label="statusInfo(row.sub)!.label"
					/>
				</div>
				<div class="truncate pl-6 text-p-sm text-ink-gray-5">
					{{ serverSubtitle(row.sub) }}
				</div>
			</component>
			<div class="flex shrink-0 items-center gap-2">
				<div class="text-right">
					<span
						class="block text-sm-medium tabular-nums"
						:class="isTerminated(row.sub) ? 'text-ink-gray-4' : 'text-ink-gray-9'"
					>
						{{ row.cost != null ? money(row.cost, currency) : '—' }}
					</span>
					<span
						v-if="showRate(row)"
						class="block text-p-sm tabular-nums text-ink-gray-5"
					>
						{{ money(row.sub.monthly_rate, currency, { trimTrailingZeros: true }) }}/mo
					</span>
				</div>
<<<<<<< HEAD
				<SubscriptionRowActions
					:subscription="row.sub"
					:can-manage="canManage"
					:busy="busy === row.sub.name"
					@open="$emit('open', $event)"
					@pause="$emit('pause', $event)"
					@resume="$emit('resume', $event)"
					@assign-project="$emit('assignProject', $event)"
				/>
=======
>>>>>>> develop
			</div>
		</template>

		<!-- Metered service -->
		<template v-else>
			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-2">
					<span
						class="mt-0.5 size-4 shrink-0 text-ink-gray-5"
						:class="serviceIcon(row.service)"
						aria-hidden="true"
					/>
					<span class="truncate text-base-medium text-ink-gray-9">
						{{ row.service.title || row.service.plan }}
					</span>
					<Badge
						v-if="exhausted(row.service)"
						theme="amber"
						label="Exhausted"
					/>
					<Badge
						v-else-if="overAllowance(row.service)"
						theme="amber"
						label="Over"
					/>
				</div>
				<div class="pl-6">
					<div class="truncate text-p-sm text-ink-gray-5">
						{{ usageLabel(row.service) }}
					</div>
					<div
						v-if="row.service.allowance > 0"
						class="mt-1.5 h-1 w-full max-w-56 overflow-hidden rounded-full bg-surface-gray-2"
					>
						<span
							class="block h-full rounded-full"
							:class="overAllowance(row.service) ? 'bg-surface-amber-7' : 'bg-surface-gray-10'"
							:style="{ width: `${overAllowance(row.service) ? 100 : usagePct(row.service)}%` }"
						/>
					</div>
				</div>
			</div>
			<div class="shrink-0 text-right">
				<span class="block text-sm-medium tabular-nums text-ink-gray-9">
					{{ money(row.cost ?? 0, currency) }}
				</span>
			</div>
		</template>
	</div>
</template>
