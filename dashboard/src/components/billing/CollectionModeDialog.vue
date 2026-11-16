<script setup lang="ts">
import { Alert, Button, Dialog, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { limitText } from '@/lib/collectionText'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { CollectionStatus } from '@/types/billing'

// The one place a customer picks how they pay. Prepaid and Auto Charge collect the
// same way, so they are one choice; picking it stores Prepaid.
const props = defineProps<{ status: CollectionStatus }>()
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ changed: [] }>()

const { activeTeam } = useSession()

type Choice = 'Automatic' | 'Manual'
const MODE_OF_CHOICE: Record<Choice, string> = {
	Automatic: 'Prepaid',
	Manual: 'Manual Checkout',
}

const chosen = ref<Choice | null>(null)
const formError = ref('')
watch(open, (isOpen) => {
	if (isOpen) chosen.value = props.status.choice
	formError.value = ''
})
watch(chosen, () => (formError.value = ''))

const isUnchanged = computed(() => chosen.value === props.status.choice)

// Tripped by an INR bill over the limit: the card or UPI cannot pay it, so only
// wallet credit gets an automatic payment past it.
const OVER_CEILING_REASONS = [
	'invoice_over_threshold',
	'forecast_over_threshold',
]
const isOverCeiling = computed(
	() =>
		props.status.currency === 'INR' &&
		OVER_CEILING_REASONS.includes(props.status.reason ?? ''),
)

const automaticBlurb = computed(() => {
	const s = props.status
	if (isOverCeiling.value)
		return s.threshold == null
			? __('Add credit to your wallet to cover this bill.')
			: __(
					'Add credit to your wallet to cover this bill. Your card or UPI pays only amounts up to {0}.',
					[limitText(s, s.threshold)],
				)
	if (!s.charged_method)
		return __(
			'Your wallet pays first. Add a card or UPI to pay what the wallet does not cover.',
		)
	return __('Your wallet pays first. When it is short, we charge {0}.', [
		s.charged_method,
	])
})

// Paying by hand exists for the INR limit, so other teams see only the automatic choice.
const options = computed(() =>
	[
		{
			key: 'Automatic' as Choice,
			icon: 'lucide-wallet',
			title: __('Pay automatically'),
			blurb: automaticBlurb.value,
			fit: __('Best for hands-off, predictable spending.'),
		},
		{
			key: 'Manual' as Choice,
			icon: 'lucide-receipt',
			title: __('Pay each invoice yourself'),
			blurb: __(
				'Your wallet pays first. We email you each invoice, and you pay the rest yourself, any amount.',
			),
			fit: __('Best if your usage varies a lot month to month.'),
		},
	].filter((o) => o.key === 'Automatic' || props.status.manual_offered),
)

const setMode = useCall<unknown, { team: string; mode: string }>({
	url: method(API.setCollectionMode),
	method: 'POST',
	immediate: false,
})

async function save(): Promise<void> {
	const choice = chosen.value
	if (!choice || isUnchanged.value) return
	await setMode.submit({
		team: activeTeam.value!,
		mode: MODE_OF_CHOICE[choice],
	})
	if (setMode.error) {
		formError.value = getErrorMessage(
			setMode.error,
			__('Could not update how you pay'),
		)
		return
	}
	successToast(
		choice === 'Automatic'
			? __(
					'You now pay automatically: your wallet first, then your card or UPI',
				)
			: __('You now pay each invoice yourself, after your wallet'),
	)
	open.value = false
	emit('changed')
}
</script>

<template>
	<Dialog v-model:open="open" :title="__('How do you want to pay?')">
		<template #default>
			<Alert
				v-if="formError"
				class="mb-4"
				theme="red"
				:title="__('Couldn\'t change how you pay')"
				:description="formError"
			/>
			<div class="grid gap-3" :class="{ 'sm:grid-cols-2': options.length > 1 }">
				<button
					v-for="o in options"
					:key="o.key"
					type="button"
					class="flex flex-col gap-2 rounded-6 border p-4 text-left transition-colors"
					:class="
						chosen === o.key
							? 'border-outline-gray-4 bg-surface-gray-2'
							: 'border-outline-gray-2 hover:border-outline-gray-3'
					"
					:aria-pressed="chosen === o.key"
					@click="chosen = o.key"
				>
					<span
						:class="o.icon"
						class="size-5 text-ink-gray-7"
						aria-hidden="true"
					/>
					<span class="text-base-medium text-ink-gray-9">{{ o.title }}</span>
					<span class="text-p-sm text-ink-gray-6">{{ o.blurb }}</span>
					<span class="mt-auto text-p-sm text-ink-gray-5">{{ o.fit }}</span>
				</button>
			</div>
			<p v-if="status.mandate_gap_note" class="mt-3 text-p-sm text-ink-gray-6">
				{{ status.mandate_gap_note }}
			</p>
			<p class="mt-3 text-p-sm text-ink-gray-5">
				{{ __(
						'This applies to every unpaid invoice, from its next payment. You can change it anytime on Billing > Payments.',
					) }}
			</p>
		</template>
		<template #actions>
			<Button
				variant="solid"
				:label="__('Confirm')"
				class="w-full"
				:loading="setMode.loading"
				:disabled="!chosen || isUnchanged"
				@click="save"
			/>
		</template>
	</Dialog>
</template>
