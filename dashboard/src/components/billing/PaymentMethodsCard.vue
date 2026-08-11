<script setup lang="ts">
import { Badge, Button, Dropdown, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import PaymentMethodRowActions from '@/components/billing/PaymentMethodRowActions.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { CollectionStatus, PaymentMethod } from '@/types/billing'

// Payment methods — one ordered list of the ways an invoice gets settled, with the
// chooser on top naming what goes first. Choosing changes the order and nothing
// else: no row appears or disappears because of a setting.
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

// What the top row says, and what each row is badged with.
function rankLabel(idx: number): string {
	if (creditsFirst.value) return 'Not charged'
	return idx === 0 ? 'Charged first' : `Fallback ${idx}`
}

const firstLabel = computed(() => {
	if (creditsFirst.value) return 'Prepaid credits'
	const first = ordered.value[0]
	return first ? first.display_label || first.method_type : 'Prepaid credits'
})

// The chooser lists every entry in the card, credits included — picking one is the
// same act as promoting a row, which is why the row menu offers it too.
const firstOptions = computed(() => [
	{ label: 'Prepaid credits', onClick: () => chooseCredits() },
	...ordered.value.map((pm) => ({
		label: pm.display_label || pm.method_type,
		onClick: () => makeDefault(pm),
	})),
])

async function chooseCredits(): Promise<void> {
	try {
		await setMode.submit({ team: activeTeam.value!, mode: 'Prepaid' })
		if (setMode.error) throw setMode.error
		successToast('Your balance pays the bill now.')
		await collection.reload()
	} catch (e) {
		errorToast(e, 'Could not change how you are billed.')
	}
}

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
		title-info="Credits are always spent first. What you choose here decides what covers the rest."
	>
		<template #action>
			<Button
				v-if="canManageBilling"
				variant="ghost"
				size="xs"
				icon="lucide-plus"
				:label="ordered.length ? 'Add backup method' : 'Add payment method'"
				@click="onAdd"
			/>
		</template>

		<div v-if="loading" class="space-y-3 py-1">
			<div v-for="i in 2" :key="i" class="flex items-center gap-3">
				<span
					class="size-8 shrink-0 animate-pulse rounded-md bg-surface-gray-2"
				/>
				<div class="flex-1 space-y-1.5">
					<span
						class="block h-3.5 w-32 animate-pulse rounded bg-surface-gray-2"
					/>
					<span
						class="block h-3 w-24 animate-pulse rounded bg-surface-gray-2"
					/>
				</div>
			</div>
		</div>

		<template v-else>
			<div class="flex items-center justify-between gap-3 pb-3">
				<div class="min-w-0">
					<p class="text-sm font-medium text-ink-gray-8">Charge this first</p>
					<p class="text-p-sm text-ink-gray-5">
						{{
							creditsFirst
								? 'Your balance pays the bill. Keep it topped up.'
								: "Whatever your credits don't cover goes here."
						}}
					</p>
				</div>
				<Dropdown
					v-if="canManageBilling && ordered.length"
					:options="firstOptions"
				>
					<Button :label="firstLabel">
						<template #suffix>
							<span class="lucide-chevron-down size-3.5" aria-hidden="true" />
						</template>
					</Button>
				</Dropdown>
				<span v-else class="text-p-sm text-ink-gray-6">{{ firstLabel }}</span>
			</div>

			<div class="divide-y divide-outline-gray-1 border-t border-outline-gray-1">
				<div class="flex items-center gap-3 py-2.5">
					<span
						class="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-gray-2 text-ink-gray-6"
					>
						<span class="lucide-wallet size-4" aria-hidden="true" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate text-sm font-medium text-ink-gray-9">
							Prepaid credits
						</p>
						<p class="truncate text-p-sm text-ink-gray-5">
							Balance {{ money(balance, currency) }}
						</p>
					</div>
					<Badge
						:theme="creditsFirst ? 'blue' : 'gray'"
						:label="creditsFirst ? 'Charged first' : 'Spent first'"
					/>
				</div>
				<div
					v-for="(pm, idx) in ordered"
					:key="pm.name"
					class="flex items-center gap-3 py-2.5"
				>
					<span
						class="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-gray-2 text-ink-gray-6"
					>
						<span :class="methodIcon(pm)" class="size-4" aria-hidden="true" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate text-sm font-medium text-ink-gray-9">
							{{ pm.display_label || pm.method_type }}
						</p>
						<p v-if="detail(pm)" class="truncate text-p-sm text-ink-gray-5">
							{{ detail(pm) }}
						</p>
					</div>
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
					<Badge
						:theme="!creditsFirst && idx === 0 ? 'blue' : 'gray'"
						:label="rankLabel(idx)"
					/>
					<PaymentMethodRowActions
						:method="pm"
						:can-manage="canManageBilling"
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

			<p class="mt-3 text-p-sm text-ink-gray-5">
				{{
					creditsFirst
						? 'A short balance leaves the invoice unpaid — nothing below is charged.'
						: ordered.length > 1
							? "If the one charged first can't cover the invoice, we try the next, in this order."
							: 'Add another way to pay so a failed charge has somewhere to go.'
				}}
			</p>
		</template>

		<EmptyState
			v-if="!loading && !ordered.length"
			class="mt-3 border-t border-outline-gray-1 pt-3"
			icon="lucide-credit-card"
			title="Nothing to charge after credits"
			description="Add a card or UPI Autopay and it covers whatever your balance doesn't."
		>
			<template v-if="canManageBilling" #action>
				<Button
					variant="solid"
					theme="gray"
					label="Add payment method"
					@click="onAdd"
				>
					<template #prefix
						><span class="lucide-plus size-4" aria-hidden="true" /></template
					>
				</Button>
			</template>
		</EmptyState>

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
