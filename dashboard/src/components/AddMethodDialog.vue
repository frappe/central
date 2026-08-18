<script setup lang="ts">
import {
	Button,
	Dialog,
	FormControl,
	LoadingText,
	Tooltip,
	useCall,
} from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import PaymentNetworkMark from '@/components/PaymentNetworkMark.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { useAddPaymentMethod } from '@/composables/useAddPaymentMethod'
import { useAddStripeCard } from '@/composables/useAddStripeCard'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import { errorToast } from '@/lib/toast'
import type { PaymentInstrument, PaymentMethodOptions } from '@/types/billing'

// Pick an instrument to save for auto-pay. This is the **mandate** surface (ADR
// 0023) and it is a shorter list than wallet recharge: netbanking pays once and
// cannot be saved, so it is not here at all.
//
const open = defineModel<boolean>({ default: false })
// Set when the dialog is opened from a "your card was declined" prompt, so the
// method that comes out of it records why it is on the other rail.
const props = withDefaults(defineProps<{ afterDecline?: boolean }>(), {
	afterDecline: false,
})
const emit = defineEmits<{ done: [res?: unknown] }>()
const { activeTeam } = useSession()

const params = () => ({ team: activeTeam.value! })
const options = useCall<PaymentMethodOptions, { team: string }>({
	url: method(API.paymentMethodOptions),
	params,
	immediate: false,
	refetch: true,
})
// The billing profile is the shared singleton — we only read its phone, so there
// is no need for a second fetch of the same payload.
const { profile } = useBillingOverview()
whenTeamReady(() => {
	options.reload()
})

function done(res?: unknown): void {
	open.value = false
	emit('done', res)
}

const { run, loading } = useAddPaymentMethod({ onDone: done })

// Razorpay opens its own hosted sheet on <body>. Our dialog is a modal with an
// overlay + focus trap, so leaving it open renders the sheet *behind* our overlay
// — the user has to dismiss our layers first to reach it. Drop our dialog before
// launching the sheet, and reopen it only if they cancel/it fails (on success
// `done` keeps it closed). The Stripe path stays in-dialog and never comes here.
async function launchGateway(
	methodType: string,
	contact?: string,
	instrument?: string,
): Promise<void> {
	const keepInstrument = selected.value?.instrument ?? null
	const keepPhone = phone.value
	open.value = false
	await nextTick()
	const res = await run(methodType, contact, instrument, props.afterDecline)
	if (!res) {
		open.value = true
		phone.value = keepPhone
		selected.value =
			tiles.value.find((t) => t.instrument === keepInstrument) ?? null
	}
}

const upiBlocked = computed(() => options.data && !options.data.allow_upi)

const tiles = computed(() => options.data?.instruments ?? [])
const hasUpi = computed(() =>
	tiles.value.some((t) => t.instrument.startsWith('UPI')),
)

const showTopup = ref(false)

function goToTopup(): void {
	open.value = false
	showTopup.value = true
}

function iconFor(tile: PaymentInstrument): string {
	return tile.instrument === 'UPI Autopay'
		? 'lucide-smartphone'
		: 'lucide-credit-card'
}

const marks: Record<string, ('visa' | 'mastercard' | 'rupay' | 'upi')[]> = {
	Card: ['visa', 'mastercard'],
	'RuPay Card': ['rupay'],
	'UPI Autopay': ['upi'],
}

function blockedReason(tile: PaymentInstrument): string | null {
	if (tile.instrument === 'UPI Autopay' && upiBlocked.value)
		return options.data?.upi_block_reason || 'Not available for your account yet.'
	return null
}

function infoText(tile: PaymentInstrument): string | null {
	if (tile.instrument !== 'UPI Autopay') return null
	if (options.data?.upi_limit)
		return `Mandate up to ${money(options.data.upi_limit, options.data.currency)}`
	return tile.description
}

const selected = ref<PaymentInstrument | null>(null)

function select(tile: PaymentInstrument): void {
	if (blockedReason(tile)) return
	selected.value = tile
}

watch(
	() => options.data,
	(d) => {
		if (!selected.value) return
		const fresh = d?.instruments?.find(
			(t) => t.instrument === selected.value?.instrument,
		)
		selected.value = fresh && !blockedReason(fresh) ? fresh : null
	},
)

function onContinue(): void {
	const tile = selected.value
	if (!tile || blockedReason(tile)) return
	if (tile.adapter_key === 'Stripe') {
		void startStripeMode()
		return
	}
	launchGateway(
		tile.instrument === 'UPI Autopay' ? 'UPI Autopay' : 'Card',
		phone.value.trim() || undefined,
		tile.instrument,
	)
}

const canContinue = computed(
	() =>
		!!selected.value &&
		!blockedReason(selected.value) &&
		!loading.value &&
		!(askPhone.value && !phone.value.trim()),
)

// A card mandate on the RuPay rail needs a customer contact. Phone is optional on
// the billing profile, so collect it inline when it's missing.
//
// This asks the *tile* which rail it sits on. Reading the payload's top-level
// adapter_key instead asks about the card rail, which is Stripe for every team —
// so the prompt never fired and the customer met a server error instead.
const hasPhone = computed(() => !!String(profile.data?.phone || '').trim())

function needsPhone(tile: PaymentInstrument): boolean {
	return (
		tile.adapter_key === 'Razorpay' &&
		tile.instrument !== 'UPI Autopay' &&
		!hasPhone.value
	)
}
const askPhone = computed(() => !!selected.value && needsPhone(selected.value))
const phone = ref('')

// Stripe card capture happens in an embedded Element (separate rail from
// Razorpay's hosted Checkout). We swap the method picker for the card field once
const stripeMode = ref(false)
const stripeLoading = ref(false)
const cardEl = ref<HTMLElement | null>(null)
const {
	mount: mountStripe,
	submit: submitStripe,
	destroy: destroyStripe,
	complete: stripeComplete,
	submitting: stripeSubmitting,
} = useAddStripeCard({ onDone: done })

async function startStripeMode(): Promise<void> {
	stripeMode.value = true
	stripeLoading.value = true
	await nextTick() // the Element needs its mount node in the DOM
	try {
		await mountStripe(cardEl.value!, {
			team: activeTeam.value!,
			publishableKey: options.data?.publishable_key,
		})
		if (!stripeMode.value || !open.value) destroyStripe()
	} catch (e) {
		errorToast(e, 'Could not start Stripe card setup.')
		cancelStripe()
	} finally {
		stripeLoading.value = false
	}
}

function cancelStripe(): void {
	destroyStripe()
	stripeMode.value = false
}

// On open, re-pull the currency-derived gateway options + profile: the team may
// have just completed its billing profile (picking a non-INR currency) without a
// team switch, so the reads warmed at mount would otherwise still offer the INR
// gateway. On close, tear down the Stripe Element and reset inline state so a
watch(open, (isOpen) => {
	if (isOpen) {
		options.reload()
		profile.reload()
	} else {
		destroyStripe()
		stripeMode.value = false
		stripeLoading.value = false
		phone.value = ''
		selected.value = null
	}
})
</script>

<template>
	<Dialog
		v-model:open="open"
		title="Add payment method"
		:dismissible="!stripeSubmitting"
		:show-close-button="!stripeSubmitting"
	>
		<template #default>
			<div v-if="options.loading && !options.data" class="space-y-2">
				<LoadingText :lines="3" />
			</div>

			<!-- Stripe card entry: Element renders inside the iframe Stripe hosts. -->
			<div v-else-if="stripeMode" class="space-y-3">
				<p v-if="stripeLoading" class="text-p-sm text-ink-gray-5">
					Loading secure card field…
				</p>
				<div
					ref="cardEl"
					class="rounded-4 border border-outline-gray-2 px-3 py-3"
				/>
				<p class="text-p-sm text-ink-gray-5">
					<template v-if="stripeSubmitting">
						Validating your card with a small temporary charge that's refunded
						right away. This can take a few seconds — please don't close this
						window.
					</template>
					<template v-else>
						Card details are entered on Stripe's secure field — we never see
						your card number.
					</template>
				</p>
			</div>

			<div v-else-if="options.data" class="space-y-4">
				<div class="flex items-center gap-2">
					<span
						class="lucide-lock size-3.5 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					<p class="text-p-sm text-ink-gray-5">
						Authorised on your bank's page. We never see your
						{{ hasUpi ? 'card or UPI' : 'card' }} details.
					</p>
				</div>

				<div aria-label="Payment method" class="space-y-2.5">
					<button
						v-for="tile in tiles"
						:key="tile.instrument"
						type="button"
						:aria-pressed="selected?.instrument === tile.instrument"
						class="flex w-full items-center gap-2.5 rounded-6 border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60"
						:class="
							selected?.instrument === tile.instrument
								? 'border-outline-gray-4'
								: 'border-outline-gray-2 hover:border-outline-gray-3'
						"
						:disabled="loading || !!blockedReason(tile)"
						@click="select(tile)"
					>
						<span
							:class="iconFor(tile)"
							class="size-4 shrink-0 text-ink-gray-7"
							aria-hidden="true"
						/>
						<span class="text-base font-medium text-ink-gray-9">{{
							tile.label
						}}</span>
						<Tooltip
						v-if="infoText(tile) && !blockedReason(tile)"
						:text="infoText(tile)!"
					>
							<span
								class="lucide-info size-3.5 text-ink-gray-4"
								aria-hidden="true"
							/>
						</Tooltip>
						<span
							v-if="blockedReason(tile)"
							class="ml-auto text-right text-p-sm text-ink-amber-6"
							>{{ blockedReason(tile) }}</span
						>
						<span v-else class="ml-auto flex shrink-0 items-center gap-1.5">
							<PaymentNetworkMark
								v-for="mark in marks[tile.instrument] ?? []"
								:key="mark"
								:network="mark"
							/>
						</span>
					</button>
				</div>

				<div
					v-if="askPhone"
					class="rounded-6 border border-outline-gray-2 px-4 py-3"
				>
					<FormControl
						v-model="phone"
						type="text"
						label="Phone number"
						placeholder="Mobile number"
						description="A recurring card on this rail needs a contact number. Saved to your billing profile."
					/>
				</div>

				<div v-if="options.data.note" class="flex items-center gap-2">
					<span
						class="lucide-info size-3.5 shrink-0 text-ink-gray-4"
						aria-hidden="true"
					/>
					<p class="text-p-sm text-ink-gray-5">
						Amex and Diners can't be auto-charged. Add credit instead.
					</p>
				</div>
			</div>

			<div v-else class="space-y-3">
				<p class="text-p-sm text-ink-gray-5">Couldn't load payment options.</p>
				<Button variant="subtle" label="Retry" @click="options.reload()" />
			</div>
		</template>

		<template #actions>
			<div v-if="stripeMode" class="flex justify-end gap-2">
				<Button
					variant="outline"
					label="Cancel"
					:disabled="stripeSubmitting"
					@click="cancelStripe"
				/>
				<Button
					variant="solid"
					:label="stripeSubmitting ? 'Validating…' : 'Add card'"
					:loading="stripeSubmitting"
					:disabled="!stripeComplete"
					@click="submitStripe"
				/>
			</div>
			<div v-else class="flex items-center gap-2">
				<Button
					v-if="options.data?.note"
					variant="subtle"
					label="Add credit"
					@click="goToTopup"
				/>
				<div class="flex-1" />
				<Button variant="outline" label="Cancel" @click="open = false" />
				<Button
					variant="solid"
					label="Continue"
					:loading="loading"
					:disabled="!canContinue"
					@click="onContinue"
				/>
			</div>
		</template>
	</Dialog>

	<TopupDialog
		v-model="showTopup"
		:currency="options.data?.currency || 'INR'"
		instrument="Card"
		@done="(res: unknown) => emit('done', res)"
	/>
</template>
