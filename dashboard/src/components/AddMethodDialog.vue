<script setup lang="ts">
import { Button, Dialog, FormControl, LoadingText, useCall } from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useAddPaymentMethod } from '@/composables/useAddPaymentMethod'
import { useAddStripeCard } from '@/composables/useAddStripeCard'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import { errorToast } from '@/lib/toast'
import type { BillingProfile, PaymentMethodOptions } from '@/types/billing'

// Pick a method to add, resolved from the team's billing currency. UPI Autopay is
// offered only when eligible (recurring-limit/trust gate from the backend). Stripe
// card capture happens in an embedded Element; Razorpay runs its hosted sheet.
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ done: [res?: unknown] }>()
const { activeTeam } = useSession()

const params = () => ({ team: activeTeam.value! })
const options = useCall<PaymentMethodOptions, { team: string }>({
	url: method(API.paymentMethodOptions),
	params,
	immediate: false,
	refetch: true,
})
const profile = useCall<BillingProfile, { team: string }>({
	url: method(API.billingProfile),
	params,
	immediate: false,
	refetch: true,
})
whenTeamReady(() => {
	options.reload()
	profile.reload()
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
): Promise<void> {
	open.value = false
	await nextTick()
	const res = await run(methodType, contact)
	if (!res) open.value = true
}

const upiBlocked = computed(() => options.data && !options.data.allow_upi)

// A Razorpay card mandate needs a customer contact; phone is optional on the
// profile, so collect it inline here when it's missing.
const cardNeedsPhone = computed(
	() =>
		options.data?.adapter_key === 'Razorpay' &&
		!String(profile.data?.phone || '').trim(),
)
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
	if (cardNeedsPhone.value && !phone.value.trim()) {
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
					class="rounded border border-outline-gray-2 px-3 py-3"
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
				<div>
					<p class="mb-2 text-p-sm font-medium text-ink-gray-7">
						How do you want to pay?
					</p>
					<div class="grid gap-3 sm:grid-cols-2">
						<button
							v-if="options.data.methods.includes('Card')"
							class="flex flex-col gap-1.5 rounded-lg border border-outline-gray-2 p-4 text-left transition-colors hover:border-outline-gray-3 disabled:opacity-50"
							:disabled="loading"
							@click="onCard"
						>
							<span
								class="lucide-credit-card size-5 text-ink-gray-7"
								aria-hidden="true"
							/>
							<span class="text-sm font-medium text-ink-gray-9">Card</span>
							<span class="text-p-sm text-ink-gray-5"
								>Visa, Mastercard, RuPay, Amex</span
							>
						</button>

						<button
							v-if="options.data.methods.includes('UPI Autopay')"
							class="flex flex-col gap-1.5 rounded-lg border border-outline-gray-2 p-4 text-left transition-colors hover:border-outline-gray-3 disabled:cursor-not-allowed disabled:opacity-50"
							:disabled="loading || !!upiBlocked"
							@click="launchGateway('UPI Autopay')"
						>
							<span
								class="lucide-smartphone size-5 text-ink-gray-7"
								aria-hidden="true"
							/>
							<span class="text-sm font-medium text-ink-gray-9"
								>UPI Autopay</span
							>
							<span v-if="upiBlocked" class="text-p-sm text-ink-amber-7">
								{{ options.data.upi_block_reason || 'Not available for your account yet.' }}
							</span>
							<span v-else class="text-p-sm text-ink-gray-5">
								Mandate up to
								{{ money(options.data.upi_limit, options.data.currency) }}
							</span>
						</button>
					</div>
				</div>

				<!-- Razorpay card mandates need a contact; collect it inline when missing. -->
				<div
					v-if="askPhone"
					class="space-y-2 rounded-lg border border-outline-gray-2 px-4 py-3"
				>
					<FormControl
						v-model="phone"
						type="text"
						label="Phone number"
						placeholder="Mobile number"
						description="Razorpay requires a contact for recurring card payments. Saved to your billing profile."
					/>
					<Button
						variant="solid"
						label="Continue"
						:loading="loading"
						:disabled="!phone.trim()"
						@click="launchGateway('Card', phone.trim())"
					/>
				</div>

				<!-- Resolved gateway — central picks it from your billing currency; not a
             chooser. -->
				<div
					class="flex items-center gap-2 rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-3 py-2.5"
				>
					<span
						class="lucide-lock size-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					<p class="text-p-sm text-ink-gray-6">
						You'll authorise on
						<span class="font-medium text-ink-gray-8"
							>{{ options.data.adapter_key }}</span
						>'s secure sheet — we never see your card or UPI credentials.
					</p>
				</div>
			</div>
		</template>
	</Dialog>
</template>
