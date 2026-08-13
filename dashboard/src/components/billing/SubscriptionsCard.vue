<script setup lang="ts">
import { Badge, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import SubscriptionRowActions from '@/components/billing/SubscriptionRowActions.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { SubscriptionRow } from '@/types/billing'

// Subscriptions — the active per-server plan rows the invoice line items accrue
// from, rendered as the FC v2 prototype's divide-y list (server icon, name +
// plan/region, monthly rate, ellipsis menu). The card owns the pause/resume calls
// and the destructive-style pause confirm (a local Dialog, since this app mounts
// no global <Dialogs /> container). Pause stops the linked VM.
const { subscriptions, cycleCosts } = useBillingOverview()
const { canManageBilling } = useCapabilities()

// Servers only: a subscription without an Asset is a team-level metered
// service, and those live (usage and money alike) in the Metered services
// card — listing them here too just duplicated the row with a $0/mo.
const rows = computed(() =>
	(subscriptions.data ?? []).filter((sub) => sub.has_server),
)
const loading = computed(() => subscriptions.loading && !subscriptions.data)

// What each server has actually cost so far this cycle, keyed by the same
// resource_id metering uses. The standing rate says what a full month costs; this
// says what is on the bill today — a server started (or resized) mid-month is the
// case where those differ and the customer notices.
const costByResource = computed(() => {
	const map = new Map<string, number>()
	for (const item of cycleCosts.data?.items ?? [])
		map.set(item.resource_id, item.amount)
	return map
})
function cycleCost(sub: SubscriptionRow): number | null {
	if (!sub.resource_id) return null
	return costByResource.value.get(sub.resource_id) ?? null
}

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

// One row mutates at a time; `busy` holds its name so the row can show a spinner.
const busy = ref('')
const pendingPause = ref<SubscriptionRow | null>(null)

// Title falls back server → plan → id; subtitle is "plan · region", skipping the
// plan when it is already serving as the title (a server with no friendly name).
function title(sub: SubscriptionRow): string {
	return sub.server || sub.plan_title || sub.name
}
function subtitle(sub: SubscriptionRow): string {
	const parts: string[] = []
	if (sub.plan_title && sub.plan_title !== title(sub))
		parts.push(sub.plan_title)
	if (sub.region) parts.push(sub.region)
	return parts.join(' · ') || sub.billing_cycle || 'Monthly'
}

// Display state, most-terminal first: a terminated VM reads Terminated (not
// Paused), a dunning one Suspended, a billing-paused one Paused, else its op state.
type BadgeTheme = 'gray' | 'red' | 'blue' | 'green' | 'amber' | 'violet' | 'orange'

function statusInfo(
	sub: SubscriptionRow,
): { label: string; theme: BadgeTheme } | null {
	if (sub.status === 'Terminated') return { label: 'Terminated', theme: 'red' }
	if (sub.account_standing === 'Suspended')
		return { label: 'Suspended', theme: 'orange' }
	if (!sub.enabled) return { label: 'Paused', theme: 'gray' }
	if (sub.status === 'Stopped') return { label: 'Stopped', theme: 'gray' }
	return null // Running is the norm — no badge needed
}
const isTerminated = (sub: SubscriptionRow): boolean =>
	sub.status === 'Terminated'
const isInactive = (sub: SubscriptionRow): boolean =>
	isTerminated(sub) || !sub.enabled || sub.account_standing === 'Suspended'

function priceLabel(sub: SubscriptionRow): string {
	if (isTerminated(sub) || sub.monthly_rate == null) return '—'
	return `${money(sub.monthly_rate, sub.currency, { trimTrailingZeros: true })}/mo`
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
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

function onOpen(sub: SubscriptionRow): void {
	if (sub.gateway_url) window.open(sub.gateway_url, '_blank', 'noopener')
}
</script>

<template>
	<BillingCard title="Subscriptions">
		<div v-if="loading" class="space-y-3 py-1">
			<div v-for="i in 2" :key="i" class="flex items-center gap-3">
				<span class="size-4 shrink-0 animate-pulse rounded bg-surface-gray-2" />
				<div class="flex-1 space-y-1.5">
					<span
						class="block h-3.5 w-40 animate-pulse rounded bg-surface-gray-2"
					/>
					<span
						class="block h-3 w-28 animate-pulse rounded bg-surface-gray-2"
					/>
				</div>
			</div>
		</div>

		<div v-else-if="rows.length" class="divide-y divide-outline-gray-1">
			<div
				v-for="sub in rows"
				:key="sub.name"
				class="flex items-center justify-between gap-3 py-3"
			>
				<component
					:is="sub.gateway_url ? 'button' : 'div'"
					class="group min-w-0 text-left"
					@click="onOpen(sub)"
				>
					<!-- The icon rides in the title row so flex centres it on the title
					     itself, whatever a badge does to the row's height. -->
					<div class="flex items-center gap-2">
						<span
							class="lucide-server size-4 shrink-0 text-ink-gray-5"
							aria-hidden="true"
						/>
						<span
							class="truncate text-base-medium text-ink-gray-9"
							:class="sub.gateway_url ? 'transition-colors group-hover:text-ink-gray-7' : ''"
						>
							{{ title(sub) }}
						</span>
						<Badge
							v-if="statusInfo(sub)"
							:theme="statusInfo(sub)!.theme"
							:label="statusInfo(sub)!.label"
						/>
					</div>
					<!-- pl-6 = icon (1rem) + gap-2 (0.5rem), so it sits under the title. -->
					<div class="truncate pl-6 text-p-sm text-ink-gray-5">
						{{ subtitle(sub) }}
					</div>
				</component>
				<div class="flex shrink-0 items-center gap-2">
					<div class="text-right">
						<span
							class="block text-sm-medium tabular-nums"
							:class="
                isInactive(sub) && !isTerminated(sub) && sub.monthly_rate != null
                  ? 'text-ink-gray-4 line-through'
                  : isTerminated(sub)
                    ? 'text-ink-gray-4'
                    : 'text-ink-gray-9'
              "
						>
							{{ priceLabel(sub) }}
						</span>
						<span
							v-if="cycleCost(sub) != null"
							class="block text-p-sm tabular-nums text-ink-gray-5"
						>
							{{ money(cycleCost(sub)!, sub.currency) }} so far
						</span>
					</div>
					<SubscriptionRowActions
						:subscription="sub"
						:can-manage="canManageBilling"
						:busy="busy === sub.name"
						@open="onOpen"
						@pause="onPause"
						@resume="onResume"
					/>
				</div>
			</div>
		</div>

		<EmptyState
			v-else
			icon="lucide-server"
			title="No subscriptions yet"
			description="Server plans appear here when you create a server."
		/>

		<ConfirmDialog
			v-model:target="pendingPause"
			title="Pause billing"
			:message="`Pause billing for ${pendingPause?.server || pendingPause?.plan_title || pendingPause?.name || ''}? This stops the server/VM and the site(s)/services running on it, and stops charges until you resume.`"
			confirm-label="Pause billing"
			:loading="busy === pendingPause?.name"
			@confirm="confirmPause"
		/>
	</BillingCard>
</template>
