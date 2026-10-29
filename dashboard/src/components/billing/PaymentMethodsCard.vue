<script setup lang="ts">
import { Badge, Button, Skeleton, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import PaymentMethodRowActions from '@/components/billing/PaymentMethodRowActions.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
import { money } from '@/lib/format'
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
const { methods, credit, currency, reloadMethods, reloadMoney } =
	useBillingOverview()
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

// The order is the whole point of this list, and it is the order the engine really
// uses: an invoice applies credits first, then walks the methods until one goes
// through (invoicing/lifecycle.py). So whatever leads is the primary and the rest
// are numbered fallbacks — while there is a balance that is the wallet, and when it
// runs dry the first method takes the title without anyone being asked.
// One row is the Primary and the rest are its fallbacks. While there is a balance
// the wallet holds the title, so every method is a fallback; when it runs dry the
// top method takes it.
const hasCredits = computed(() => balance.value > 0)

function methodLabel(idx: number): string {
	if (hasCredits.value) return `Fallback ${idx + 1}`
	return idx === 0 ? 'Primary' : `Fallback ${idx}`
}

// Every row labelled a fallback can be made the primary. While credits are paying
// the bill the choice decides nothing yet, so it is disabled rather than hidden.
function isPrimaryRow(idx: number): boolean {
	return !hasCredits.value && idx === 0
}

async function makeDefault(pm: PaymentMethod): Promise<void> {
	busy.value = pm.name
	try {
		await setDefault.submit({ payment_method: pm.name })
		if (setDefault.error) throw setDefault.error
		// Charging this first only means something if anything is charged at all, so
		// a prepaid team comes off prepaid by asking for it.
		if (creditsFirst.value) {
			await setMode.submit({ team: activeTeam.value!, mode: 'Auto Charge' })
			if (setMode.error) throw setMode.error
		}
		successToast(`${pm.display_label || pm.method_type} is charged first`)
		await collection.reload()
		reloadMethods()
	} catch (e) {
		reportError(e)
	} finally {
		busy.value = ''
	}
}

async function confirmRemove(pm: PaymentMethod): Promise<void> {
	busy.value = pm.name
	removeError.value = ''
	try {
		await remove.submit({ payment_method: pm.name })
		if (remove.error) throw remove.error
		successToast('Payment method removed')
		pendingRemove.value = null
		reloadMethods()
	} catch (e) {
		removeError.value = getErrorMessage(
			e,
			"The payment method couldn't be removed.",
		)
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
		if (reorder.error) throw reorder.error
		reloadMethods()
	} catch (e) {
		reportError(e)
	} finally {
		busy.value = ''
	}
}

const showAdd = ref(false)
const removeError = ref('')
watch(pendingRemove, () => (removeError.value = ''))
function onAdd(): void {
	if (requireSetup()) showAdd.value = true
}
const showTopup = ref(false)
const onTopUp = () => {
	if (requireSetup()) showTopup.value = true
}
</script>

<template>
	<BillingCard title="Payment methods">
		<div v-if="loading" class="flex flex-col gap-2.5">
			<Skeleton v-for="i in 2" :key="i" class="h-14 rounded-5" />
		</div>

		<ul v-else class="flex flex-col gap-2.5">
			<li
				class="flex items-center gap-3 rounded-5 border border-outline-gray-1 p-3"
			>
				<span
					class="grid size-8 shrink-0 place-items-center rounded-4 bg-surface-gray-2"
				>
					<span
						class="lucide-wallet size-4 text-ink-gray-6"
						aria-hidden="true"
					/>
				</span>
				<div class="min-w-0 flex-1">
					<div class="text-base text-ink-gray-9">Prepaid credits</div>
					<div class="mt-0.5 text-sm tabular-nums text-ink-gray-5">
						{{ money(balance, currency) }}
						balance
					</div>
				</div>
				<span v-if="hasCredits" class="text-sm text-ink-gray-5"> Primary </span>
				<Button
					v-if="canManageBilling"
					size="sm"
					label="Top up"
					@click="onTopUp"
				/>
			</li>

			<li
				v-for="(pm, idx) in ordered"
				:key="pm.name"
				class="flex items-center gap-3 rounded-5 border border-outline-gray-1 p-3"
			>
				<span
					class="grid size-8 shrink-0 place-items-center rounded-4 bg-surface-gray-2"
				>
					<span
						:class="methodIcon(pm)"
						class="size-4 text-ink-gray-6"
						aria-hidden="true"
					/>
				</span>
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-2">
						<span class="truncate text-base text-ink-gray-9">
							{{ pm.display_label || pm.method_type }}
						</span>
						<Badge
							v-if="pm.reauth_required"
							theme="amber"
							label="Re-auth needed"
						/>
						<Badge v-else-if="pm.status !== 'Active'" :label="pm.status" />
					</div>
					<div
						v-if="detail(pm)"
						class="mt-0.5 truncate text-sm text-ink-gray-5"
					>
						{{ detail(pm) }}
					</div>
				</div>
				<span class="text-sm text-ink-gray-5">
					{{ methodLabel(idx) }}
				</span>
				<PaymentMethodRowActions
					:method="pm"
					:can-manage="canManageBilling"
					:is-primary="isPrimaryRow(idx)"
					:can-promote="!hasCredits"
					:is-first="idx === 0"
					:is-last="idx === ordered.length - 1"
					:busy="busy === pm.name"
					@make-default="makeDefault"
					@move-up="(m) => move(m, -1)"
					@move-down="(m) => move(m, 1)"
					@remove="pendingRemove = $event"
				/>
			</li>

			<li v-if="canManageBilling">
				<button
					type="button"
					class="flex w-full items-center gap-3 rounded-5 border border-dashed border-outline-gray-2 p-3 text-left transition-colors hover:bg-surface-gray-1"
					@click="onAdd"
				>
					<span
						class="grid size-8 shrink-0 place-items-center rounded-4 border border-dashed border-outline-gray-2"
					>
						<span
							class="lucide-plus size-3.5 text-ink-gray-5"
							aria-hidden="true"
						/>
					</span>
					<span class="min-w-0 flex-1">
						<span class="block text-base text-ink-gray-9">
							{{ ordered.length ? 'Add another card' : 'Add a card' }}
						</span>
						<span class="mt-0.5 block text-sm text-ink-gray-5">
							{{ ordered.length
									? 'Used if the ones above fail'
									: 'Pays invoices automatically on the due date' }}
						</span>
					</span>
				</button>
			</li>
		</ul>

		<p
			v-if="!loading"
			class="mt-auto flex items-start gap-1.5 pt-4 text-p-sm text-ink-gray-6"
		>
			<span
				class="lucide-arrow-down-wide-narrow mt-0.5 size-3.5 shrink-0 text-ink-gray-4"
				aria-hidden="true"
			/>
			Invoices use credits first, then payment methods in the order shown.
		</p>

		<ConfirmDialog
			v-model:target="pendingRemove"
			title="Remove payment method"
			:message="`Remove ${pendingRemove?.display_label || pendingRemove?.name || ''}? Invoices will fall back to your other methods, if any.`"
			confirm-label="Remove"
			theme="red"
			:loading="busy === pendingRemove?.name"
			:error="removeError"
			@confirm="confirmRemove"
		/>
		<AddMethodDialog v-model="showAdd" @done="reloadMethods" />
		<TopupDialog v-model="showTopup" :currency="currency" @done="reloadMoney" />
	</BillingCard>
</template>
