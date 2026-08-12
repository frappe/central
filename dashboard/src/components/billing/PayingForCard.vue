<script setup lang="ts">
import { Badge, Button, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import SubscriptionRowActions from '@/components/billing/SubscriptionRowActions.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { SubscriptionRow } from '@/types/billing'

// What you're paying for — servers and team-level metered services in one list,
// each row carrying what it has cost SO FAR this cycle. A customer asking the
// question does not care that one has an Asset behind it and the other is a
// synthesized subject (ADR 0013).
//
// The two were separate cards because listing a service beside servers used to
// duplicate it at a standing rate of zero — a service has no monthly rate, only
// usage. That is fixed here by ranking on cycle-to-date cost instead: a metered
// row shows what it has actually cost and how far into its allowance it is, which
// is the number it does have.
//
// The rows stay typed underneath: pause/resume and "open server" are server verbs
// and only render on server rows; subscribing to a service happens on the Add-ons
// page, which is where the header action points. One list, two row kinds.
interface ServiceRow {
	service_subject: string
	plan: string
	title: string | null
	resource_type: string | null
	cluster: string | null
	currency: string
	unit: string | null
	settlement_mode: string
	allowance: number
	period_usage: number
}

type Row =
	| { kind: 'server'; id: string; cost: number | null; sub: SubscriptionRow }
	| { kind: 'service'; id: string; cost: number | null; service: ServiceRow }

const { subscriptions, cycleCosts } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { activeTeam } = useSession()
const router = useRouter()

const services = useCall<{ services: ServiceRow[] }, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => services.reload())

const loading = computed(
	() =>
		(subscriptions.loading && !subscriptions.data) ||
		(services.loading && !services.data),
)

const costById = computed(() => {
	const map = new Map<string, number>()
	for (const item of cycleCosts.data?.items ?? []) map.set(item.resource_id, item.amount)
	return map
})

// Most expensive first — the question behind the card is "where is the money
// going", and that is the order that answers it.
const rows = computed<Row[]>(() => {
	const servers: Row[] = (subscriptions.data ?? [])
		.filter((sub) => sub.has_server)
		.map((sub) => ({
			kind: 'server' as const,
			id: sub.name,
			cost: sub.resource_id ? (costById.value.get(sub.resource_id) ?? null) : null,
			sub,
		}))
	const metered: Row[] = (services.data?.services ?? []).map((service) => ({
		kind: 'service' as const,
		id: service.service_subject,
		cost: costById.value.get(service.service_subject) ?? null,
		service,
	}))
	return [...servers, ...metered].sort((a, b) => (b.cost ?? 0) - (a.cost ?? 0))
})

const currency = computed(
	() => cycleCosts.data?.currency ?? subscriptions.data?.[0]?.currency ?? 'INR',
)
const total = computed(() => Number(cycleCosts.data?.total ?? 0))

// ── server rows ──────────────────────────────────────────────────────────────
const pause = useCall<unknown, { subscription: string }>({
	url: method(API.pauseSubscription),
	method: 'POST',
	immediate: false,
})
const resume = useCall<unknown, { subscription: string }>({
	url: method(API.resumeSubscription),
	method: 'POST',
	immediate: false,
})
const busy = ref('')
const pendingPause = ref<SubscriptionRow | null>(null)

type BadgeTheme = 'gray' | 'red' | 'blue' | 'green' | 'amber' | 'violet' | 'orange'

function serverTitle(sub: SubscriptionRow): string {
	return sub.server || sub.plan_title || sub.name
}
function serverSubtitle(sub: SubscriptionRow): string {
	const parts: string[] = []
	if (sub.plan_title && sub.plan_title !== serverTitle(sub)) parts.push(sub.plan_title)
	if (sub.region) parts.push(sub.region)
	return parts.join(' · ') || sub.billing_cycle || 'Monthly'
}
function statusInfo(sub: SubscriptionRow): { label: string; theme: BadgeTheme } | null {
	if (sub.status === 'Terminated') return { label: 'Terminated', theme: 'red' }
	if (sub.account_standing === 'Suspended') return { label: 'Suspended', theme: 'orange' }
	if (!sub.enabled) return { label: 'Paused', theme: 'gray' }
	if (sub.status === 'Stopped') return { label: 'Stopped', theme: 'gray' }
	return null
}
const isTerminated = (sub: SubscriptionRow): boolean => sub.status === 'Terminated'

function onOpen(sub: SubscriptionRow): void {
	if (sub.gateway_url) window.open(sub.gateway_url, '_blank', 'noopener')
}
function onPause(sub: SubscriptionRow): void {
	pendingPause.value = sub
}
async function confirmPause(sub: SubscriptionRow): Promise<void> {
	pendingPause.value = null
	busy.value = sub.name
	try {
		await pause.submit({ subscription: sub.name })
		successToast('Billing paused, server stopping…')
		subscriptions.reload()
		cycleCosts.reload()
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}
async function onResume(sub: SubscriptionRow): Promise<void> {
	busy.value = sub.name
	try {
		await resume.submit({ subscription: sub.name })
		successToast('Billing resumed, server starting…')
		subscriptions.reload()
		cycleCosts.reload()
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

// ── service rows ─────────────────────────────────────────────────────────────
function serviceIcon(row: ServiceRow): string {
	const key = `${row.resource_type || ''} ${row.title || ''}`.toLowerCase()
	if (/token|ai/.test(key)) return 'lucide-sparkles'
	if (/pdf|print/.test(key)) return 'lucide-file-text'
	if (/mail/.test(key)) return 'lucide-mail'
	if (/storage|object/.test(key)) return 'lucide-archive'
	return 'lucide-gauge'
}
function usageLabel(row: ServiceRow): string {
	const unit = row.unit || 'units'
	if (row.settlement_mode === 'Prepaid Pack' && row.allowance) {
		const remaining = Math.max(0, row.allowance - row.period_usage)
		return `${remaining.toLocaleString()} / ${row.allowance.toLocaleString()} ${unit} left`
	}
	const included = row.allowance ? ` of ${row.allowance.toLocaleString()} incl.` : ''
	return `${row.period_usage.toLocaleString()} ${unit}${included}`
}
function exhausted(row: ServiceRow): boolean {
	return (
		row.settlement_mode === 'Prepaid Pack' &&
		row.allowance > 0 &&
		row.period_usage >= row.allowance
	)
}
// Draw-down against the included allowance. Past 100% the bar fills and turns —
// the overage is what the row's cost is made of.
function usagePct(row: ServiceRow): number {
	if (!row.allowance) return 0
	return Math.min(100, Math.round((row.period_usage / row.allowance) * 100))
}
function overAllowance(row: ServiceRow): boolean {
	return row.allowance > 0 && row.period_usage > row.allowance
}

function goToAddons(): void {
	router.push({ name: 'Addons' })
}
</script>

<template>
	<BillingCard
		title="What you're paying for"
		:description="
      total > 0 ? `${money(total, currency)} so far this cycle` : undefined
    "
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
				<span class="size-4 shrink-0 animate-pulse rounded bg-surface-gray-2" />
				<div class="flex-1 space-y-1.5">
					<span class="block h-3.5 w-40 animate-pulse rounded bg-surface-gray-2" />
					<span class="block h-3 w-28 animate-pulse rounded bg-surface-gray-2" />
				</div>
			</div>
		</div>

		<div v-else-if="rows.length" class="divide-y divide-outline-gray-1">
			<div
				v-for="row in rows"
				:key="row.id"
				class="flex items-center justify-between gap-3 py-3"
			>
				<!-- Server row -->
				<template v-if="row.kind === 'server'">
					<component
						:is="row.sub.gateway_url ? 'button' : 'div'"
						class="group min-w-0 text-left"
						@click="onOpen(row.sub)"
					>
						<div class="flex items-center gap-2">
							<span
								class="lucide-server size-4 shrink-0 text-ink-gray-5"
								aria-hidden="true"
							/>
							<span
								class="truncate text-base-medium text-ink-gray-9"
								:class="
                  row.sub.gateway_url
                    ? 'transition-colors group-hover:text-ink-gray-7'
                    : ''
                "
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
								v-if="row.sub.monthly_rate != null && !isTerminated(row.sub)"
								class="block text-p-sm tabular-nums text-ink-gray-5"
							>
								{{ money(row.sub.monthly_rate, currency, { trimTrailingZeros: true }) }}/mo
							</span>
						</div>
						<SubscriptionRowActions
							:subscription="row.sub"
							:can-manage="canManageBilling"
							:busy="busy === row.sub.name"
							@open="onOpen"
							@pause="onPause"
							@resume="onResume"
						/>
					</div>
				</template>

				<!-- Service row -->
				<template v-else>
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span
								class="size-4 shrink-0 text-ink-gray-5"
								:class="serviceIcon(row.service)"
								aria-hidden="true"
							/>
							<span class="truncate text-base-medium text-ink-gray-9">
								{{ row.service.title || row.service.plan }}
							</span>
							<Badge v-if="exhausted(row.service)" theme="orange" label="Exhausted" />
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
							<!-- The draw-down bar: how far into the included allowance this
							     service is. Only where there IS an allowance to draw down. -->
							<!-- Same meter the servers page uses: ink-gray-8 on surface-gray-2.
							     Over the allowance the fill goes amber-6, which is the first
							     amber with enough contrast to read as a warning — the -2/-3
							     tints are banner backgrounds and vanish at this height. -->
							<div
								v-if="row.service.allowance > 0"
								class="mt-1.5 h-1 w-full max-w-56 overflow-hidden rounded-full bg-surface-gray-2"
							>
								<span
									class="block h-full rounded-full"
									:class="
                    overAllowance(row.service) ? 'bg-surface-amber-7' : 'bg-surface-gray-10'
                  "
									:style="{
                    width: `${overAllowance(row.service) ? 100 : usagePct(row.service)}%`,
                  }"
								/>
							</div>
						</div>
					</div>
					<div class="shrink-0 text-right">
						<span class="block text-sm-medium tabular-nums text-ink-gray-9">
							{{ row.cost != null ? money(row.cost, currency) : money(0, currency) }}
						</span>
						<span class="block text-p-sm text-ink-gray-5">metered</span>
					</div>
				</template>
			</div>
		</div>

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
	</BillingCard>
</template>
