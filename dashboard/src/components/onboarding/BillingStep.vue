<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import BillingCountryField from '@/components/billing/BillingCountryField.vue'
import PaymentMethodFlow from '@/components/billing/PaymentMethodFlow.vue'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { formatDate, money } from '@/lib/format'
import type { WelcomeCredit } from '@/types/billing'

const { profile, currency } = useBillingSetup()
const flow = ref<InstanceType<typeof PaymentMethodFlow> | null>(null)
const hasMethod = ref(false)

// The offer is gone from the profile once the credit is granted, so keep the last one seen
// to confirm it after the payment method is added.
const offer = ref<WelcomeCredit | null>(null)
watch(
	() => profile.value?.welcome_credit,
	(credit) => {
		if (credit) offer.value = credit
	},
	{ immediate: true },
)
const offerAmount = computed(() =>
	offer.value
		? money(offer.value.amount, offer.value.currency, {
				trimTrailingZeros: true,
			})
		: '',
)
// The two limits on the offer, each shown only when it applies.
const offerFacts = computed(() => {
	if (!offer.value) return []
	const facts: { icon: string; text: string }[] = []
	if (offer.value.ends_on)
		facts.push({
			icon: 'lucide-calendar',
			text: `Add one by ${formatDate(offer.value.ends_on)}`,
		})
	if (offer.value.validity_days)
		facts.push({
			icon: 'lucide-clock',
			text: `Use it within ${offer.value.validity_days} days`,
		})
	return facts
})

const steps = computed(() => [
	{
		icon: 'lucide-credit-card',
		title: 'No charge today',
		// Razorpay takes ₹1 to set up UPI Autopay or a card mandate; Central refunds it.
		text:
			currency.value === 'INR'
				? 'We save it and check that it works. UPI and some cards take ₹1 to set up. We refund it.'
				: 'We save it and check that it works.',
	},
	{
		icon: 'lucide-wallet',
		title: 'Credit pays first',
		text: offer.value
			? `Your ${offerAmount.value} credit pays for your servers before your card does.`
			: 'Any credit in your wallet pays for your servers before your card does.',
	},
	{
		icon: 'lucide-receipt',
		title: 'Then pay monthly',
		text: 'We charge only what your credit does not cover, with your monthly invoice.',
	},
])

defineExpose({
	canSubmit: true,
	submitLabel: computed(() =>
		hasMethod.value ? 'Continue' : 'Add payment method',
	),
	saving: false,
	submit: async () => {
		if (hasMethod.value) return true
		flow.value?.start()
		return false
	},
})
</script>

<template>
	<div class="space-y-5">
		<BillingCountryField v-if="!hasMethod" />
		<div
			v-if="hasMethod"
			class="flex items-start gap-3 rounded-6 bg-surface-green-1 px-4 py-3"
			role="status"
		>
			<span
				class="lucide-circle-check mt-0.5 size-4 shrink-0 text-ink-green-3"
				aria-hidden="true"
			/>
			<p class="text-p-sm text-ink-gray-8">
				<span class="text-p-sm-medium text-ink-gray-9"
					>Payment method added.</span
				>
				{{ offer
						? `Your ${offerAmount} credit is in your wallet.`
						: 'You can now create servers.' }}
			</p>
		</div>
		<div v-else-if="offer" class="rounded-6 bg-surface-gray-2 p-4">
			<div class="flex items-start justify-between gap-4">
				<div>
					<p class="text-base-medium text-ink-gray-9">Welcome credit</p>
					<p class="mt-1 text-p-sm text-ink-gray-6">
						Your first payment method unlocks it.
					</p>
				</div>
				<p class="text-2xl-semibold tabular-nums text-ink-gray-9">
					{{ offerAmount }}
				</p>
			</div>
			<ul
				v-if="offerFacts.length"
				class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-p-sm text-ink-gray-6"
			>
				<li
					v-for="fact in offerFacts"
					:key="fact.icon"
					class="flex items-center gap-1.5"
				>
					<span
						:class="fact.icon"
						class="size-3.5 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					{{ fact.text }}
				</li>
			</ul>
		</div>

		<section aria-labelledby="billing-how-it-works">
			<h4 id="billing-how-it-works" class="text-sm-medium text-ink-gray-5">
				How billing works
			</h4>
			<ol class="mt-3 space-y-4">
				<li
					v-for="step in steps"
					:key="step.title"
					class="flex items-start gap-3"
				>
					<span
						class="flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-gray-2"
						aria-hidden="true"
					>
						<span :class="step.icon" class="size-3.5 text-ink-gray-7" />
					</span>
					<div>
						<p class="text-sm-medium text-ink-gray-9">{{ step.title }}</p>
						<p class="mt-0.5 text-p-sm text-ink-gray-6">{{ step.text }}</p>
					</div>
				</li>
			</ol>
		</section>

		<PaymentMethodFlow ref="flow" @done="hasMethod = true" />
	</div>
</template>
