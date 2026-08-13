<script setup lang="ts">
import { Button, Dialog, FormControl, LoadingText, useCall } from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useAddPaymentMethod } from '@/composables/useAddPaymentMethod'
import TopupDialog from '@/components/TopupDialog.vue'
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
// The tiles come from the backend and the instrument decides the rail. Our card
// rail registers mandates on Visa and Mastercard only, so every other network is a
// separate tile on the other rail — named, not detected, because Stripe Elements
// iframes the card number. Stripe capture happens in an embedded Element; Razorpay
// runs its hosted sheet.
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
	open.value = false
	await nextTick()
	const res = await run(methodType, contact, instrument, props.afterDecline)
	if (!res) open.value = true
}

const upiBlocked = computed(() => options.data && !options.data.allow_upi)

const tiles = computed(() => options.data?.instruments ?? [])

// A card no rail will hold a mandate on has one honest destination, so the line
// saying so *is* the way there: tap it and the top-up opens. Our dialog closes
// first — two stacked modals is how the second one ends up behind the first.
const showTopup = ref(false)

function goToTopup(): void {
	open.value = false
	showTopup.value = true
}

const icons: Record<string, string> = {
	Card: 'lucide-credit-card',
	'RuPay Card': 'lucide-credit-card',
	'UPI Autopay': 'lucide-smartphone',
}

// A tile the customer can't act on right now, with the reason to show in its place.
function blockedReason(tile: PaymentInstrument): string | null {
	if (tile.instrument === 'UPI Autopay' && upiBlocked.value)
		return options.data?.upi_block_reason || 'Not available for your account yet.'
	return null
}

function subtitle(tile: PaymentInstrument): string {
	if (tile.instrument === 'UPI Autopay' && options.data?.upi_limit)
		return `Mandate up to ${money(options.data.upi_limit, options.data.currency)}`
	return tile.description
}

function choose(tile: PaymentInstrument): void {
	if (blockedReason(tile)) return
	if (tile.adapter_key === 'Stripe') {
		onCard()
		return
	}
	if (needsPhone(tile) && !phone.value.trim()) {
		askPhone.value = true
		return
	}
	launchGateway(
		tile.instrument === 'UPI Autopay' ? 'UPI Autopay' : 'Card',
		phone.value.trim() || undefined,
		tile.instrument,
	)
}

// A card mandate on the RuPay rail needs a customer contact. Phone is optional on
// the billing profile, so collect it inline when it's missing.
//
// This asks the *tile* which rail it sits on. Reading the payload's top-level
// adapter_key instead asks about the card rail, which is Stripe for every team —
// so the prompt never fired and the customer met a server error instead.
const hasPhone = computed(() => !!String(profile.data?.phone || '').trim())

function needsPhone(tile: PaymentInstrument): boolean {
	return tile.adapter_key === 'Razorpay' && tile.instrument !== 'UPI Autopay' && !hasPhone.value
}
const askPhone = ref(false)
const phone = ref('')

// Stripe card capture happens in an embedded Element (separate rail from
// Razorpay's hosted Checkout). We swap the method picker for the card field once
// the customer chooses Card on a Stripe gateway.
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

async function startStripe(): Promise<void> {
	stripeLoading.value = true
	await nextTick() // the Element needs its mount node in the DOM
	try {
		await mountStripe(cardEl.value!, {
			team: activeTeam.value!,
			publishableKey: options.data?.publishable_key,
		})
	} catch (e) {
		errorToast(e, 'Could not start Stripe card setup.')
		cancelStripe()
	} finally {
		stripeLoading.value = false
	}
}

async function onCard(): Promise<void> {
	if (options.data?.adapter_key === 'Stripe') {
		stripeMode.value = true
		await startStripe()
		return
	}
	if (!hasPhone.value && !phone.value.trim() && options.data?.adapter_key === 'Razorpay') {
		askPhone.value = true
		return
	}
	launchGateway('Card', phone.value.trim() || undefined)
}

function cancelStripe(): void {
	destroyStripe()
	stripeMode.value = false
}

// On open, re-pull the currency-derived gateway options + profile: the team may
// have just completed its billing profile (picking a non-INR currency) without a
// team switch, so the reads warmed at mount would otherwise still offer the INR
// gateway. On close, tear down the Stripe Element and reset inline state so a
// reopen starts on the method picker (not a stale Stripe field).
watch(open, (isOpen) => {
	if (isOpen) {
		options.reload()
		profile.reload()
	} else {
		destroyStripe()
		stripeMode.value = false
		stripeLoading.value = false
		askPhone.value = false
		phone.value = ''
	}
})
</script>

<template>
	<Dialog v-model:open="open" title="Add payment method">
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
				<div class="flex gap-2">
					<Button
						variant="solid"
						:label="stripeSubmitting ? 'Validating…' : 'Add card'"
						:loading="stripeSubmitting"
						:disabled="!stripeComplete"
						@click="submitStripe"
					/>
					<Button
						label="Cancel"
						:disabled="stripeSubmitting"
						@click="cancelStripe"
					/>
				</div>
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
				<!-- No "how do you want to pay" heading — the dialog title and the
				     two option cards already say it. -->
				<div>
					<div class="grid gap-3 sm:grid-cols-2">
						<button
							v-for="tile in tiles"
							:key="tile.instrument"
							class="flex flex-col gap-1.5 rounded-6 border border-outline-gray-2 p-4 text-left transition-colors hover:border-outline-gray-3 disabled:cursor-not-allowed disabled:opacity-50"
							:disabled="loading || !!blockedReason(tile)"
							@click="choose(tile)"
						>
							<span
								:class="icons[tile.instrument] || 'lucide-credit-card'"
								class="size-5 text-ink-gray-7"
								aria-hidden="true"
							/>
							<span class="text-sm font-medium text-ink-gray-9">{{
								tile.label
							}}</span>
							<span
								v-if="blockedReason(tile)"
								class="text-p-sm text-ink-amber-6"
								>{{ blockedReason(tile) }}</span
							>
							<span v-else class="text-p-sm text-ink-gray-5">{{
								subtitle(tile)
							}}</span>
						</button>
					</div>
					<button
						v-if="options.data.note"
						type="button"
						class="mt-3 flex w-full items-center justify-center gap-1.5 text-p-sm text-ink-gray-6 underline decoration-outline-gray-3 underline-offset-4 hover:text-ink-gray-8"
						@click="goToTopup"
					>
						{{ options.data.note }}
						<span class="lucide-arrow-right size-3.5" aria-hidden="true" />
					</button>
				</div>

				<!-- Razorpay card mandates need a contact; collect it inline when missing. -->
				<div
					v-if="askPhone"
					class="space-y-2 rounded-6 border border-outline-gray-2 px-4 py-3"
				>
					<FormControl
						v-model="phone"
						type="text"
						label="Phone number"
						placeholder="Mobile number"
						description="A recurring card on this rail needs a contact number. Saved to your billing profile."
					/>
					<Button
						variant="solid"
						label="Continue"
						:loading="loading"
						:disabled="!phone.trim()"
						@click="launchGateway('Card', phone.trim(), 'RuPay Card')"
					/>
				</div>

				<!-- The customer chose an instrument, not a provider, and two tiles here
             may sit on different providers, so this line names neither. Flat
             footer, not a box. -->
				<div class="flex items-center gap-2 pt-1">
					<span
						class="lucide-lock size-3.5 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					<p class="text-p-sm text-ink-gray-5">
						You'll authorise this on your bank's or card network's secure page.
						We never see your card or UPI details.
					</p>
				</div>
			</div>
		</template>
	</Dialog>

	<!-- Opened from the Amex/Diners line above, after this dialog has closed. -->
	<TopupDialog
		v-model="showTopup"
		:currency="options.data?.currency || 'INR'"
		instrument="Card"
		@done="(res: unknown) => emit('done', res)"
	/>
</template>
