<script setup lang="ts">
import { Badge, Button, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'

// Metered services (ADR 0015) — the team-level services it has subscribed to (AI
// tokens, email, PDF, storage), each with its allowance draw-down / usage this
// period, plus a subscribe/upgrade action. A metered service has no VM: it is a
// synthesized subject billed off the same rollup + price-lock spine as a server.
interface ServiceRow {
	service_subject: string
	plan: string
	title: string | null
	resource_type: string | null
	cluster: string | null
	currency: string
	unit: string | null
	billing_type: string | null
	settlement_mode: string
	reporting_mode: string
	allowance: number
	period_usage: number
}
interface MeteredServices {
	currency: string
	services: ServiceRow[]
}

const { canManageBilling } = useCapabilities()
const { activeTeam } = useSession()
const router = useRouter()
const { cycleCosts, currency } = useBillingOverview()

// A metered service showed its draw-down but never what it had cost — the one
// question the card was silent on. Joined on service_subject, which is the
// resource_id metering and the cycle-cost read both key on (ADR 0013).
const costBySubject = computed(() => {
	const map = new Map<string, number>()
	for (const item of cycleCosts.data?.items ?? [])
		map.set(item.resource_id, item.amount)
	return map
})
function cycleCost(row: ServiceRow): number | null {
	return costBySubject.value.get(row.service_subject) ?? null
}

const data = useCall<MeteredServices, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => data.reload())

const loading = computed(() => data.loading && !data.data)
const rows = computed(() => data.data?.services ?? [])

// Subscribing happens on the Add-ons page (plan browsing lives there) — this
// card only reports usage, so both Subscribe actions are links, not a dialog.
function goToAddons(): void {
	router.push({ name: 'Addons' })
}

// The title line already names the service — the subtext carries only what's
// new (the region), or nothing.
function subtitle(row: ServiceRow): string {
	return row.cluster || ''
}

// Each add-on family keeps the icon it wears on the Add-ons pages; the gauge
// is only the unknown-service fallback.
function serviceIcon(row: ServiceRow): string {
	const key = `${row.resource_type || ''} ${row.title || ''}`.toLowerCase()
	if (/token|ai/.test(key)) return 'lucide-sparkles'
	if (/pdf|print/.test(key)) return 'lucide-file-text'
	if (/mail/.test(key)) return 'lucide-mail'
	if (/storage|object/.test(key)) return 'lucide-archive'
	return 'lucide-gauge'
}

// A prepaid pack shows remaining allowance; a postpaid meter shows usage this period.
function usageLabel(row: ServiceRow): string {
	const unit = row.unit || 'units'
	if (row.settlement_mode === 'Prepaid Pack' && row.allowance) {
		const remaining = Math.max(0, row.allowance - row.period_usage)
		return `${remaining.toLocaleString()} / ${row.allowance.toLocaleString()} ${unit} left`
	}
	const included = row.allowance
		? ` of ${row.allowance.toLocaleString()} incl.`
		: ''
	return `${row.period_usage.toLocaleString()} ${unit}${included} this period`
}

function exhausted(row: ServiceRow): boolean {
	return (
		row.settlement_mode === 'Prepaid Pack' &&
		row.allowance > 0 &&
		row.period_usage >= row.allowance
	)
}
</script>

<template>
	<BillingCard
		title="Metered services"
		title-info="Team-level services billed by usage (AI tokens, email, PDF, storage) — no server required."
	>
		<template v-if="canManageBilling" #action>
			<Button
				variant="ghost"
				size="xs"
				icon="lucide-plus"
				title="Subscribe"
				label="Subscribe"
				@click="goToAddons"
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
						class="block h-3 w-28 animate-pulse rounded-4 bg-surface-gray-2"
					/>
				</div>
			</div>
		</div>

		<div v-else-if="rows.length" class="divide-y divide-outline-gray-1">
			<div
				v-for="row in rows"
				:key="row.service_subject"
				class="flex items-center justify-between gap-3 py-3"
			>
				<div class="min-w-0">
					<!-- The icon rides in the title row so flex centres it on the title
					     itself, whatever a badge does to the row's height. -->
					<div class="flex items-center gap-2">
						<span
							class="size-4 shrink-0 text-ink-gray-5"
							:class="serviceIcon(row)"
							aria-hidden="true"
						/>
						<span class="truncate text-base-medium text-ink-gray-9">
							{{ row.title || row.plan }}
						</span>
						<Badge v-if="exhausted(row)" theme="amber" label="Exhausted" />
						<Badge
							v-else-if="row.settlement_mode === 'Prepaid Pack'"
							theme="blue"
							label="Prepaid"
						/>
					</div>
					<!-- pl-6 = icon (1rem) + gap-2 (0.5rem), so it sits under the title. -->
					<div
						v-if="subtitle(row)"
						class="truncate pl-6 text-p-sm text-ink-gray-5"
					>
						{{ subtitle(row) }}
					</div>
				</div>
				<div class="shrink-0 text-right">
					<span
						v-if="cycleCost(row) != null"
						class="block text-sm-medium tabular-nums text-ink-gray-9"
					>
						{{ money(cycleCost(row)!, currency) }}
					</span>
					<span
						class="block tabular-nums"
						:class="
              cycleCost(row) != null
                ? 'text-p-sm text-ink-gray-5'
                : 'text-sm-medium text-ink-gray-9'
            "
					>
						{{ usageLabel(row) }}
					</span>
				</div>
			</div>
		</div>

		<EmptyState
			v-else
			icon="lucide-gauge"
			title="No metered services"
			description="Subscribe to a usage-billed service like AI tokens, email, or PDF rendering."
		>
			<template v-if="canManageBilling" #action>
				<Button variant="subtle" label="Subscribe" @click="goToAddons" />
			</template>
		</EmptyState>
	</BillingCard>
</template>
