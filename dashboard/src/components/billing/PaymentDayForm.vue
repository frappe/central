<script setup lang="ts">
import { Alert, Button, LoadingText, Select, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useCapabilities } from '@/composables/useCapabilities'
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
const { canManageBilling } = useCapabilities()

const LAST_PAYMENT_DAY = 10
const options = Array.from({ length: LAST_PAYMENT_DAY }, (_, index) => ({
	label: `${ordinal(index + 1)} of the month`,
	value: String(index + 1),
}))

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

const draft = ref('1')
const formError = ref('')

watch(
	() => props.open,
	(isOpen) => {
		if (isOpen && activeTeam.value) settings.reload()
	},
	{ immediate: true },
)

watch(
	() => settings.data,
	(data) => {
		if (data) draft.value = String(data.payment_day || 1)
	},
)

watch(draft, () => (formError.value = ''))

const changesLeft = computed(() => settings.data?.payment_day_changes_left ?? 0)
const isUnchanged = computed(
	() => Number(draft.value) === (settings.data?.payment_day ?? 1),
)
const canChange = computed(
	() => canManageBilling.value && changesLeft.value > 0,
)

const hint = computed(() => {
	if (!canManageBilling.value)
		return 'Only team members who manage billing can change the payment date.'
	if (!changesLeft.value)
		return "You've changed the payment date twice this billing cycle. You can change it again next month."

	const times = changesLeft.value === 1 ? 'once more' : 'twice'

	return `Wallet credit is used on the 1st. We charge the rest on this day. You can change it ${times} this billing cycle.`
})

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

	<form v-else class="flex flex-col gap-3" @submit.prevent="submit">
		<Alert v-if="formError" theme="red" :title="formError" />

		<Select
			v-model="draft"
			:options="options"
			:disabled="!canChange"
			label="Payment date"
			:description="hint"
		/>

		<div v-if="canChange" class="flex justify-end">
			<Button
				type="submit"
				variant="solid"
				label="Save payment date"
				:disabled="isUnchanged"
				:loading="save.loading"
			/>
		</div>
	</form>
</template>
