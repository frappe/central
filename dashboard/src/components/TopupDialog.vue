<script setup lang="ts">
import { Button, Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, nextTick, type Ref, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { useTopup } from '@/composables/useTopup'
import { currencySymbol, money } from '@/lib/format'
import { errorToast } from '@/lib/toast'
import type { PaymentInstrument } from '@/types/billing'

// Amount entry → in-app payment. Shared by the wallet card and credits surface.
//
// This is the **recharge** surface (ADR 0023), which is not the same list as saving
// a method for auto-pay: netbanking can top up a wallet but cannot be saved. The
// customer picks the instrument and that decides the rail, so a card reaches Stripe
// even though Razorpay owns the INR default. Stripe collects the card in an embedded
// Element right here; Razorpay collects in its hosted sheet; PayPal renders its
// Buttons in a second phase. The wallet is credited only after the gateway confirms.
// `instrument` is set when the caller already knows what the customer is paying
// with — the Amex/Diners route says so by arriving here at all. Asking again is
// the whole reason that route felt broken, so the picker is skipped and the
// instrument is stated instead.
const props = withDefaults(
	defineProps<{ currency?: string; instrument?: string }>(),
	{ currency: 'INR', instrument: undefined },
)
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ done: [res?: unknown] }>()

const amount = ref<number | null>(null)
const presets = [1000, 5000, 10000, 25000]

const { activeTeam } = useSession()
const options = useCall<{ instruments: PaymentInstrument[] }, { team: string }>(
	{
		url: method(API.topupOptions),
		params: () => ({ team: activeTeam.value! }),
		immediate: false,
		refetch: true,
	},
)
const instruments = computed(() => options.data?.instruments ?? [])
const instrument = ref<string | null>(null)

// A caller-supplied instrument is fixed unless the customer asks to change it.
const fixed = ref(false)
const chosenLabel = computed(
	() =>
		instruments.value.find((t) => t.instrument === instrument.value)?.label ??
		instrument.value ??
		'',
)
const icons: Record<string, string> = {
	Card: 'lucide-credit-card',
	'RuPay Card': 'lucide-credit-card',
	UPI: 'lucide-smartphone',
	Netbanking: 'lucide-landmark',
}

// Payment rail. INR always uses the Razorpay sheet; international currencies use a
// card (Stripe Element). PayPal (directly settled, ADR 0007) is temporarily hidden
// — its gateway + Buttons plumbing is kept intact (useTopup.mountPayPal) so it can
// be re-enabled by flipping this flag.
const PAYPAL_ENABLED = false
const payMethod = ref<'card' | 'paypal'>('card')
// With PayPal hidden, foreign currencies have only the Stripe card rail, so there
// is no rail to choose between.
const showMethodChoice = computed(
	() => props.currency !== 'INR' && PAYPAL_ENABLED,
)

// Second-phase mount targets: Stripe card Element / PayPal Buttons.
const cardPhase = ref(false)
const cardLoading = ref(false)
const cardEl = ref<HTMLElement | null>(null)
const paypalPhase = ref(false)
const paypalLoading = ref(false)
const paypalEl = ref<HTMLElement | null>(null)

// Set when the wallet is actually credited, so a Razorpay top-up that runs with
// the dialog closed knows whether to reopen (customer backed out) or stay closed.
let completed = false
const {
	begin,
	mountCard,
	mountPayPal,
	pay,
	destroy,
	cardComplete,
	submitting,
	loading,
} = useTopup({
	onDone: (res) => {
		completed = true
		open.value = false
		emit('done', res)
	},
})

async function submit(): Promise<void> {
	const value = Number(amount.value)
	if (!value || value <= 0) return
	// PayPal is only offered for international currencies; INR stays on the default rail.
	const chosen =
		showMethodChoice.value && payMethod.value === 'paypal'
			? 'paypal'
			: undefined
	completed = false
	// On the Razorpay rail begin() invokes onSheet before opening the hosted sheet —
	// drop our modal so the sheet is reachable, and reopen it if the customer cancels.
	const { card, paypal } = await begin(
		value,
		chosen,
		() => {
			open.value = false
		},
		instrument.value ?? undefined,
	)
	if (paypal)
		return enterPhase(
			paypalPhase,
			paypalLoading,
			paypalEl,
			mountPayPal,
			'Could not start PayPal',
		)
	if (card)
		return enterPhase(
			cardPhase,
			cardLoading,
			cardEl,
			mountCard,
			'Could not start secure card entry',
		)
	// else: the Razorpay sheet ran with our dialog closed — reopen it unless the
	// top-up went through (onDone already closed and flagged it).
	if (!completed) open.value = true
}

// Switch to a second-phase view and mount its gateway widget into the fresh node.
async function enterPhase(
	phase: Ref<boolean>,
	loadingRef: Ref<boolean>,
	elRef: Ref<HTMLElement | null>,
	mount: (el: HTMLElement) => Promise<void> | Promise<unknown>,
	failMsg: string,
): Promise<void> {
	phase.value = true
	loadingRef.value = true
	await nextTick() // the widget needs its mount node in the DOM
	try {
		await mount(elRef.value!)
	} catch (e) {
		errorToast(e, failMsg)
		phase.value = false
	} finally {
		loadingRef.value = false
	}
}

// Reset to the amount step whenever the dialog closes, tearing down any widget so
// a reopen never shows a stale card field / buttons.
watch(open, (isOpen) => {
	if (isOpen) {
		options.reload()
		if (props.instrument) {
			instrument.value = props.instrument
			fixed.value = true
		}
		return
	}
	if (!isOpen) {
		destroy()
		amount.value = null
		instrument.value = null
		fixed.value = false
		payMethod.value = 'card'
		cardPhase.value = false
		cardLoading.value = false
		paypalPhase.value = false
		paypalLoading.value = false
	}
})
</script>

<template>
	<Dialog v-model:open="open" title="Top up wallet">
		<template #default>
			<!-- Stripe card entry: Element renders inside the iframe Stripe hosts. -->
			<div v-if="cardPhase" class="space-y-3">
				<p class="text-sm text-ink-gray-8">
					Paying {{ money(Number(amount), currency) }}
				</p>
				<p v-if="cardLoading" class="text-p-sm text-ink-gray-5">
					Loading secure card field…
				</p>
				<div
					ref="cardEl"
					class="rounded-4 border border-outline-gray-2 px-3 py-3"
				/>
				<p class="text-p-sm text-ink-gray-5">
					Card details are entered on Stripe's secure field. We never see your
					card number. Your billing address is taken from your billing profile.
				</p>
			</div>

			<!-- PayPal entry: PayPal Buttons render here; approval happens in PayPal's popup. -->
			<div v-else-if="paypalPhase" class="space-y-3">
				<p class="text-sm text-ink-gray-8">
					Paying {{ money(Number(amount), currency) }}
				</p>
				<p v-if="paypalLoading" class="text-p-sm text-ink-gray-5">
					Loading PayPal…
				</p>
				<div ref="paypalEl" />
				<p class="text-p-sm text-ink-gray-5">
					You'll approve the payment in PayPal. Your wallet is credited only
					after PayPal confirms.
				</p>
			</div>

			<div v-else class="space-y-5">
				<!-- The recharge instruments. Each sits on its own rail, so this is not
             decoration: it decides where the money goes. -->
				<!-- Already told which instrument: say it, don't ask it again. -->
				<div
					v-if="fixed"
					class="flex items-center gap-2 rounded-6 border border-outline-gray-2 bg-surface-gray-1 px-3 py-2.5"
				>
					<span
						:class="icons[instrument || ''] || 'lucide-credit-card'"
						class="size-4 shrink-0 text-ink-gray-6"
						aria-hidden="true"
					/>
					<p class="text-p-sm text-ink-gray-6">
						Paying with your {{ chosenLabel.toLowerCase() }}
					</p>
					<Button
						class="ml-auto"
						variant="ghost"
						size="sm"
						label="Change"
						@click="fixed = false"
					/>
				</div>

				<div v-else-if="instruments.length > 1">
					<p class="mb-1.5 text-p-sm text-ink-gray-5">Pay with</p>
					<div class="grid gap-2 sm:grid-cols-2">
						<button
							v-for="tile in instruments"
							:key="tile.instrument"
							class="flex items-center gap-2 rounded-6 border p-3 text-left transition-colors"
							:class="
								instrument === tile.instrument
									? 'border-outline-gray-4 bg-surface-gray-1'
									: 'border-outline-gray-2 hover:border-outline-gray-3'
							"
							@click="instrument = tile.instrument"
						>
							<span
								:class="icons[tile.instrument] || 'lucide-credit-card'"
								class="size-4 shrink-0 text-ink-gray-7"
								aria-hidden="true"
							/>
							<span class="text-sm text-ink-gray-9">{{ tile.label }}</span>
						</button>
					</div>
				</div>
				<div v-if="showMethodChoice">
					<p class="mb-1.5 text-p-sm text-ink-gray-5">Pay with</p>
					<div class="flex gap-2">
						<Button
							label="Card"
							:variant="payMethod === 'card' ? 'solid' : 'subtle'"
							@click="payMethod = 'card'"
						/>
						<Button
							label="PayPal"
							:variant="payMethod === 'paypal' ? 'solid' : 'subtle'"
							@click="payMethod = 'paypal'"
						/>
					</div>
				</div>
				<div>
					<p class="mb-1.5 text-p-sm text-ink-gray-5">Amount</p>
					<div class="mb-2 flex flex-wrap gap-2">
						<Button
							v-for="p in presets"
							:key="p"
							:label="`${currencySymbol(currency)}${p.toLocaleString()}`"
							:variant="Number(amount) === p ? 'solid' : 'subtle'"
							@click="amount = p"
						/>
					</div>
					<FormControl
						v-model="amount"
						type="number"
						label="Amount"
						:placeholder="`Enter amount in ${currency}`"
						min="1"
					/>
				</div>
				<p class="text-p-sm text-ink-gray-5">
					You'll complete payment securely. Your wallet is credited only after
					the payment is confirmed.
				</p>
			</div>
		</template>
		<template #actions>
			<Button
				v-if="cardPhase"
				variant="solid"
				:label="submitting ? 'Paying…' : 'Pay'"
				:loading="submitting"
				:disabled="!cardComplete"
				class="w-full"
				@click="pay"
			/>
			<!-- PayPal phase: the PayPal Buttons are the action; no footer button. -->
			<Button
				v-else-if="!paypalPhase"
				variant="solid"
				label="Continue to payment"
				:loading="loading"
				:disabled="!amount || Number(amount) <= 0"
				class="w-full"
				@click="submit"
			/>
		</template>
	</Dialog>
</template>
