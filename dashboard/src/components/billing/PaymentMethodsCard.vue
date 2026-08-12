<script setup lang="ts">
import { Badge, Button, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import PaymentMethodRowActions from '@/components/billing/PaymentMethodRowActions.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { CollectionStatus, PaymentMethod } from '@/types/billing'

// Payment methods — one ordered list of the ways an invoice gets settled. Each row
// carries its own control, so the order is set where it is read rather than in a
// separate chooser above the thing it governs.
//
// Credits lead by default because a new team is granted some, and while they last
// they are what pays the bill. They also pay what they can when they are short —
// the remainder is charged to a saved method, or left for the customer to settle
// if nothing is saved.
//
// Everything below the first entry exists for one reason: a card that fails should
// not end in suspension. That is what the fallback order buys, and it is why the
// list is worth having to a team that only ever uses one card.
//
// Prepaid credits are the first entry because the engine spends them before it
// charges anything (the credits waterfall, credits.md). Choosing credits as the
// one charged first means the opposite of a fallback — it says *don't* auto-charge
// what the balance can't cover — so the rows below then read "not charged" rather
// than pretending to be rungs the engine would try.
//
// The card owns the calls and the destructive remove confirm (a local Dialog, since
// this app mounts no global <Dialogs /> container).
const { activeTeam } = useSession()
const { methods, credit, currency, reloadMethods } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const ordered = computed(() => methods.data ?? [])
const loading = computed(() => methods.loading && !methods.data)

const setDefault = useCall<unknown, { payment_method: string }>({
	url: method(API.setDefaultPaymentMethod),
	method: 'POST',
	immediate: false,
})
const remove = useCall<unknown, { payment_method: string }>({
	url: method(API.removePaymentMethod),
	method: 'POST',
	immediate: false,
})
const reorder = useCall<unknown, { team: string; ordered: string[] }>({
	url: method(API.reorderPaymentMethods),
	method: 'POST',
	immediate: false,
})

// One row mutates at a time; `busy` holds its name so the row can show a spinner.
const busy = ref('')
const pendingRemove = ref<PaymentMethod | null>(null)

function methodIcon(pm: PaymentMethod): string {
	return pm.method_type === 'Card' ? 'lucide-credit-card' : 'lucide-smartphone'
}

// The second line has to say something the first one doesn't. A method with no
// label of its own is titled by its type, so repeating the type underneath ("UPI
// Autopay / UPI Autopay") is noise — that row shows the ceiling the bank will let
// us debit instead, or nothing at all.
function detail(pm: PaymentMethod): string {
	const parts: string[] = []
	if (pm.display_label) parts.push(pm.method_type)
	if (pm.expiry_month && pm.expiry_year)
		parts.push(
			`expires ${String(pm.expiry_month).padStart(2, '0')}/${pm.expiry_year}`,
		)
	if (pm.mandate_max_amount)
		parts.push(
			`up to ${money(pm.mandate_max_amount, pm.mandate_currency || currency.value)} per debit`,
		)
	return parts.join(' · ')
}

const balance = computed(() => Number(credit.data?.balance ?? 0))

// Which entry is charged first. Credits win whenever the team is prepaid; otherwise
// the primary method does, and credits are still spent first by the engine — the
// difference the customer feels is whether anything gets charged at all.
const creditsFirst = computed(() => collectionMode.value === 'Prepaid')

const collection = useCall<CollectionStatus, { team: string }>({
	url: method(API.collectionStatus),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => collection.reload())
const collectionMode = computed(() => collection.data?.collection_mode ?? '')

const setMode = useCall<unknown, { team: string; mode: string }>({
	url: method(API.setCollectionMode),
	method: 'POST',
	immediate: false,
})

// The order is the whole point of this list, and a number says it without a word.
// Credits are step 1 because the engine spends them before it charges anything;
// each method follows in the order it is tried.

// Choosing which method gets charged decides nothing while there is a balance to
// spend, so the action is offered and disabled rather than hidden.
const canPromote = computed(() => balance.value <= 0)

async function makeDefault(pm: PaymentMethod): Promise<void> {
	busy.value = pm.name
	try {
		await setDefault.submit({ payment_method: pm.name })
		// Charging this first only means something if anything is charged at all, so
		// a prepaid team comes off prepaid by asking for it.
		if (creditsFirst.value) {
			await setMode.submit({ team: activeTeam.value!, mode: 'Auto Charge' })
			if (setMode.error) throw setMode.error
		}
		successToast(`${pm.display_label || pm.method_type} is charged first.`)
		await collection.reload()
		reloadMethods()
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

async function confirmRemove(pm: PaymentMethod): Promise<void> {
	busy.value = pm.name
	try {
		await remove.submit({ payment_method: pm.name })
		successToast('Payment method removed')
		pendingRemove.value = null
		reloadMethods()
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

// Move a method up/down in the fallback order, then persist the whole order.
async function move(pm: PaymentMethod, delta: number): Promise<void> {
	const list = ordered.value.map((m) => m.name)
	const index = list.indexOf(pm.name)
	const target = index + delta
	if (index < 0 || target < 0 || target >= list.length) return
	;[list[index], list[target]] = [list[target], list[index]]
	busy.value = pm.name
	try {
		await reorder.submit({ team: activeTeam.value!, ordered: list })
		reloadMethods()
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

const showAdd = ref(false)
function onAdd(): void {
	if (requireSetup()) showAdd.value = true
}
</script>

<template>
	<BillingCard
		title="Payment methods"
		title-info="Settled in this order: credits first, then each method until one goes through."
	>
		<template v-if="canManageBilling" #action>
			<Button
				size="xs"
				:label="ordered.length ? 'Add method' : 'Add payment method'"
				icon-left="lucide-plus"
				@click="onAdd"
			/>
		</template>

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

		<template v-else>
			<div class="divide-y divide-outline-gray-1">
				<div class="flex items-center justify-between gap-3 py-3">
					<div class="flex min-w-0 items-start gap-2.5">
						<span
							class="mt-0.5 w-3 shrink-0 text-p-sm tabular-nums text-ink-gray-4"
							aria-hidden="true"
						>
							1
						</span>
						<span
							class="lucide-wallet mt-0.5 size-4 shrink-0 text-ink-gray-5"
							aria-hidden="true"
						/>
						<div class="min-w-0">
							<span class="truncate text-sm font-medium text-ink-gray-9">
								Prepaid credits
							</span>
							<div class="truncate text-p-sm text-ink-gray-5">
								Balance {{ money(balance, currency) }}
							</div>
						</div>
					</div>
					<!-- Holds the column so this row lines up with ones that have a menu. -->
					<span class="size-7 shrink-0" aria-hidden="true" />
				</div>
				<div
					v-for="(pm, idx) in ordered"
					:key="pm.name"
					class="flex items-center justify-between gap-3 py-3"
				>
					<div class="flex min-w-0 items-start gap-2.5">
						<span
							class="mt-0.5 w-3 shrink-0 text-p-sm tabular-nums text-ink-gray-4"
							aria-hidden="true"
						>
							{{ idx + 2 }}
						</span>
						<span
							:class="methodIcon(pm)"
							class="mt-0.5 size-4 shrink-0 text-ink-gray-5"
							aria-hidden="true"
						/>
						<div class="min-w-0">
							<div class="flex items-center gap-2">
								<span class="truncate text-sm font-medium text-ink-gray-9">
									{{ pm.display_label || pm.method_type }}
								</span>
								<Badge
									v-if="pm.reauth_required"
									theme="orange"
									label="Re-auth needed"
								/>
								<Badge
									v-else-if="pm.status !== 'Active'"
									theme="gray"
									:label="pm.status"
								/>
							</div>
							<div v-if="detail(pm)" class="truncate text-p-sm text-ink-gray-5">
								{{ detail(pm) }}
							</div>
						</div>
					</div>
					<div class="flex shrink-0 items-center gap-1">
						<PaymentMethodRowActions
							:method="pm"
							:can-manage="canManageBilling"
							:can-promote="canPromote"
							:is-first="idx === 0"
							:is-last="idx === ordered.length - 1"
							:busy="busy === pm.name"
							@make-default="makeDefault"
							@move-up="(m) => move(m, -1)"
							@move-down="(m) => move(m, 1)"
							@remove="pendingRemove = $event"
						/>
					</div>
				</div>
			</div>

		</template>


		<ConfirmDialog
			v-model:target="pendingRemove"
			title="Remove payment method"
			:message="`Remove ${pendingRemove?.display_label || pendingRemove?.name || ''}? Invoices will fall back to your other methods, if any.`"
			confirm-label="Remove"
			theme="red"
			:loading="busy === pendingRemove?.name"
			@confirm="confirmRemove"
		/>
		<AddMethodDialog v-model="showAdd" @done="reloadMethods" />
	</BillingCard>
</template>
