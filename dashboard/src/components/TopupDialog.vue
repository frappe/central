<script setup lang="ts">
import {
	Alert,
	Button,
	Dialog,
	Radio,
	RadioGroup,
	TextInput,
	useCall,
} from 'frappe-ui'
import { computed, nextTick, type Ref, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import PaymentNetworkMark, {
	type PaymentNetwork,
} from '@/components/PaymentNetworkMark.vue'
import { useSession } from '@/composables/useSession'
import { useTopup } from '@/composables/useTopup'
import { getErrorMessage } from '@/lib/feedback'
import { currencySymbol, money } from '@/lib/format'
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

const amount = ref<number>()
const presets = [1000, 5000, 10000, 25000]

const { activeTeam } = useSession()
const options = useCall<
	{ instruments: PaymentInstrument[]; gst_rate: number },
	{ team: string }
>({
	url: method(API.topupOptions),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
const instruments = computed(() => options.data?.instruments ?? [])
// GST is charged on top of a top-up; the wallet is credited the amount entered.
const gstRate = computed(() => options.data?.gst_rate ?? 0)
const gst = computed(
	() => Math.round(Number(amount.value || 0) * gstRate.value) / 100,
)
const payable = computed(() => Number(amount.value || 0) + gst.value)
const instrument = ref<string | null>(null)
// Start on the first instrument, so the form never opens with nothing chosen. Only
// while open: a default set while closed would block the caller's instrument.
function pickFirstInstrument(): void {
	if (open.value && !instrument.value && instruments.value.length)
		instrument.value = instruments.value[0].instrument
}
// The first open has no cached list yet, so pick once the options arrive.
watch(instruments, pickFirstInstrument)

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
const marks: Record<string, PaymentNetwork[]> = {
	Card: ['visa', 'mastercard'],
	'RuPay Card': ['rupay', 'diners'],
	UPI: ['upi'],
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

// Set when the wallet is credited. The close for a Razorpay success happens while
// inSheet is set, so the watcher skips reset and submit() resets the form instead.
let completed = false
// True while the Razorpay sheet runs with our dialog closed. The dialog keeps the
// amount and method, so a customer who comes back retries without starting over.
let inSheet = false
const {
	begin,
	mountCard,
	mountPayPal,
	pay,
	destroy,
	cardComplete,
	submitting,
	loading,
	error: paymentError,
	clearError,
} = useTopup({
	onDone: (res) => {
		completed = true
		open.value = false
		emit('done', res)
	},
})
const dialogError = ref('')
const visibleError = computed(() => dialogError.value || paymentError.value)

watch([amount, instrument, payMethod], () => {
	dialogError.value = ''
	clearError()
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
			inSheet = true
			open.value = false
		},
		instrument.value ?? undefined,
	)
	inSheet = false
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
	// The Razorpay sheet ran with the dialog closed, so the watcher kept the form.
	// Reset it after a success; reopen it with the error after a cancel or failure.
	if (completed) reset()
	else open.value = true
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
		dialogError.value = getErrorMessage(e, failMsg)
		phase.value = false
	} finally {
		loadingRef.value = false
	}
}

// Reset to the amount step, tearing down any widget so a reopen never shows a
// stale card field / buttons.
function reset(): void {
	destroy()
	amount.value = undefined
	instrument.value = null
	fixed.value = false
	payMethod.value = 'card'
	cardPhase.value = false
	cardLoading.value = false
	paypalPhase.value = false
	paypalLoading.value = false
	dialogError.value = ''
}

watch(open, (isOpen) => {
	if (!isOpen) {
		if (!inSheet) reset()
		return
	}
	options.reload()
	// A return from the Razorpay sheet keeps the customer's pick and its error;
	// only a fresh open (form reset, so no instrument) takes the caller's instrument.
	if (props.instrument && !instrument.value) {
		instrument.value = props.instrument
		fixed.value = true
	}
	// A reopen reuses the cached list, since the reload may not change or may fail.
	pickFirstInstrument()
})
</script>

<template>
	<Dialog v-model:open="open" title="Top up wallet">
		<template #default>
			<Alert
				v-if="visibleError"
				class="mb-4"
				theme="red"
				title="Couldn't top up your wallet"
				:description="visibleError"
			/>
			<!-- Stripe card entry: Element renders inside the iframe Stripe hosts. -->
			<div v-if="cardPhase" class="space-y-3">
				<p class="text-sm text-ink-gray-8">
					Paying {{ money(payable, currency) }}
				</p>
				<p v-if="cardLoading" class="text-p-sm text-ink-gray-6">
					Loading secure card field…
				</p>
				<div
					ref="cardEl"
					class="rounded-4 border border-outline-gray-2 px-3 py-3"
				/>
				<p class="text-p-sm text-ink-gray-6">
					Card details are entered on Stripe's secure field. We never see your
					card number. Your billing address is taken from your billing profile.
				</p>
			</div>

			<!-- PayPal entry: PayPal Buttons render here; approval happens in PayPal's popup. -->
			<div v-else-if="paypalPhase" class="space-y-3">
				<p class="text-sm text-ink-gray-8">
					Paying {{ money(payable, currency) }}
				</p>
				<p v-if="paypalLoading" class="text-p-sm text-ink-gray-6">
					Loading PayPal…
				</p>
				<div ref="paypalEl" />
				<p class="text-p-sm text-ink-gray-6">
					You'll approve the payment in PayPal. Your wallet is credited only
					after PayPal confirms.
				</p>
			</div>

			<div v-else class="space-y-5">
				<div>
					<TextInput
						v-model="amount"
						autofocus
						type="number"
						label="Amount"
						placeholder="0"
						min="1"
					>
						<template #prefix>
							<span class="text-sm text-ink-gray-5"
								>{{ currencySymbol(currency) }}</span
							>
						</template>
					</TextInput>
					<div
						class="mt-2 grid grid-cols-4 gap-2"
						role="group"
						aria-label="Quick amounts"
					>
						<Button
							v-for="preset in presets"
							:key="preset"
							:label="money(preset, currency, { trimTrailingZeros: true })"
							@click="amount = preset"
						/>
					</div>
				</div>

				<!-- Already told which instrument: say it, don't ask it again. -->
				<div
					v-if="fixed"
					class="flex items-center gap-3 rounded-6 border border-outline-gray-2 px-3 py-2.5"
				>
					<span
						:class="icons[instrument || ''] || 'lucide-credit-card'"
						class="size-4 shrink-0 text-ink-gray-6"
						aria-hidden="true"
					/>
					<p class="text-p-sm text-ink-gray-7">
						Paying with your {{ chosenLabel.toLowerCase() }}
					</p>
					<Button
						class="ml-auto"
						variant="ghost"
						label="Change"
						@click="fixed = false"
					/>
				</div>

				<!-- Each instrument sits on its own rail, so the choice decides where the money goes. -->
				<RadioGroup
					v-else-if="instruments.length > 1"
					v-model="instrument"
					label="Pay with"
					size="md"
					padded
				>
					<Radio
						v-for="tile in instruments"
						:key="tile.instrument"
						:value="tile.instrument"
					>
						<template #label>
							<span class="flex items-center gap-2.5">
								{{ tile.label }}
								<PaymentNetworkMark
									v-for="mark in marks[tile.instrument] ?? []"
									:key="mark"
									:network="mark"
								/>
							</span>
						</template>
					</Radio>
				</RadioGroup>

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

				<dl
					v-if="Number(amount) > 0"
					class="space-y-1.5 rounded-6 bg-surface-gray-1 px-3 py-2.5 text-p-sm"
				>
					<div v-if="gstRate" class="flex justify-between">
						<dt class="text-ink-gray-6">Wallet credit</dt>
						<dd class="tabular-nums text-ink-gray-8">
							{{ money(Number(amount), currency) }}
						</dd>
					</div>
					<div v-if="gstRate" class="flex justify-between">
						<dt class="text-ink-gray-6">GST ({{ gstRate }}%)</dt>
						<dd class="tabular-nums text-ink-gray-8">
							{{ money(gst, currency) }}
						</dd>
					</div>
					<div class="flex justify-between text-p-sm-medium">
						<dt class="text-ink-gray-8">You pay</dt>
						<dd class="tabular-nums text-ink-gray-9">
							{{ money(payable, currency) }}
						</dd>
					</div>
				</dl>
				<p class="text-p-sm text-ink-gray-6">
					We add the credit to your wallet once the payment goes through.
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
