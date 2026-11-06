<script setup lang="ts">
import { Alert, Button, LoadingText, Select, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { ordinal } from '@/lib/date'
import { getErrorMessage, successToast } from '@/lib/feedback'
import type { BillingSettings } from '@/types/billing'

interface Props {
	open: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ saved: [] }>()

const { activeTeam } = useSession()

const settings = useCall<BillingSettings, { team: string }>({
	url: method(API.billingSettings),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
})

const save = useCall<unknown, { team: string; payment_day: number }>({
	url: method(API.saveBillingSettings),
	method: 'POST',
	immediate: false,
})

const draft = ref('')
const formError = ref('')

// A team switch drops the draft so the old team's choice is never saved to the new one.
watch(
	[() => props.open, activeTeam],
	([isOpen, team], previous) => {
		if (previous && team !== previous[1]) {
			draft.value = ''
			formError.value = ''
		}
		if (isOpen && team) settings.reload()
	},
	{ immediate: true },
)

watch(
	() => settings.data,
	(data) => {
		if (data) draft.value = String(data.payment_day)
	},
)

watch(draft, () => (formError.value = ''))

const options = computed(() =>
	Array.from({ length: settings.data?.last_payment_day ?? 0 }, (_, index) => ({
		label: `${ordinal(index + 1)} of the month`,
		value: String(index + 1),
	})),
)

const changesPerCycle = computed(
	() => settings.data?.payment_day_changes_per_cycle ?? 0,
)
const changesLeft = computed(() => settings.data?.payment_day_changes_left ?? 0)
const isUnchanged = computed(
	() => Number(draft.value) === settings.data?.payment_day,
)
const canChange = computed(() => changesLeft.value > 0)

const hint = computed(() => {
	if (!changesLeft.value)
		return `You've changed the payment date ${timesLabel(changesPerCycle.value)} this billing cycle. You can change it again next month.`

	const times =
		changesLeft.value < changesPerCycle.value
			? `${timesLabel(changesLeft.value)} more`
			: timesLabel(changesLeft.value)

	return `Wallet credit is used on the 1st. We charge the rest on this day. You can change it ${times} this billing cycle.`
})

// A payment day after the last one with interval retries gets one retry, 24 hours later.
const oneRetryWarning = computed(() => {
	const data = settings.data
	if (!data || Number(draft.value) <= data.last_payment_day_with_retries)
		return null

	return `If the charge on this day fails, we try once more after 24 hours. Your servers stop on the ${ordinal(data.suspension_day)} if the invoice stays unpaid.`
})

function timesLabel(count: number): string {
	if (count === 1) return 'once'
	if (count === 2) return 'twice'

	return `${count} times`
}

async function submit(): Promise<void> {
	try {
		await save.submit({
			team: activeTeam.value!,
			payment_day: Number(draft.value),
		})

		if (save.error) throw save.error

		successToast('Payment date saved')
		settings.reload()
		emit('saved')
	} catch (error) {
		formError.value = getErrorMessage(
			error,
			"The payment date couldn't be saved.",
		)
	}
}
</script>

<template>
	<LoadingText v-if="settings.loading && !settings.data" :lines="2" />

	<Alert
		v-else-if="settings.error && !settings.data"
		theme="red"
		title="The payment date couldn't load"
		:description="getErrorMessage(settings.error, 'Try again in a moment.')"
		:primary-action="{ label: 'Retry', onClick: () => settings.reload() }"
	/>

	<form
		v-else-if="settings.data"
		class="flex flex-col gap-3"
		@submit.prevent="submit"
	>
		<Alert
			v-if="formError"
			theme="red"
			title="Couldn't change the payment date"
			:description="formError"
		/>

		<Select
			v-model="draft"
			:options="options"
			:disabled="!canChange"
			label="Payment date"
			:description="hint"
		/>

		<Alert
			v-if="oneRetryWarning"
			theme="amber"
			title="This day gets one retry"
			:description="oneRetryWarning"
		/>

		<div v-if="canChange" class="flex justify-end">
			<Button
				type="submit"
				variant="solid"
				label="Save payment date"
				:disabled="isUnchanged || settings.loading"
				:loading="save.loading"
			/>
		</div>
	</form>
</template>
