<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { errorToast } from '@/lib/toast'
import type { PaymentMethod } from '@/types/billing'

// Earmark a payment method to a Billing Group, or clear it back into the team's
// general (untagged) pool. Controlled by the card: pass the pending method (or
// null) via v-model:method, mirroring AssignBillingGroupDialog for subscriptions.
// A group's own earmarked method is tried first when its invoice is charged,
// falling back to the team's general methods (ARCHITECTURE.md §2.1) — this is
// "which card funds that group's invoice first", not a payment-order change.
const GENERAL = ''

const props = defineProps<{ method: PaymentMethod | null }>()
const emit = defineEmits<{
	'update:method': [pm: PaymentMethod | null]
	assigned: []
}>()

const { groups } = useBillingOverview()

const open = computed({
	get: () => !!props.method,
	set: (v: boolean) => {
		if (!v) emit('update:method', null)
	},
})

const selected = ref(GENERAL)
watch(
	() => props.method,
	(pm) => {
		if (pm) selected.value = pm.billing_group || GENERAL
	},
)

const options = computed(() => [
	{ label: 'General (no group)', value: GENERAL },
	...(groups.data ?? [])
		.filter((g) => g.enabled)
		.map((g) => ({ label: g.title, value: g.name })),
])

const canSubmit = computed(
	() => selected.value !== (props.method?.billing_group || GENERAL),
)

const assign = useCall<unknown, { payment_method: string; billing_group: string | null }>({
	url: method(API.setPaymentMethodBillingGroup),
	method: 'POST',
	immediate: false,
})

async function submit(): Promise<void> {
	if (!props.method || !canSubmit.value) return
	try {
		await assign.submit({
			payment_method: props.method.name,
			billing_group: selected.value || null,
		})
		if (assign.error) throw assign.error
		emit('update:method', null)
		emit('assigned')
	} catch (e) {
		errorToast(e)
	}
}

const dialogOptions = computed(() => ({
	title: 'Earmark to a billing group',
	actions: [
		{
			label: 'Save',
			variant: 'solid' as const,
			loading: assign.loading,
			disabled: !canSubmit.value,
			onClick: submit,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:actions="dialogOptions.actions"
	>
		<template #default>
			<FormControl
				type="select"
				v-model="selected"
				:options="options"
				label="Billing group"
				description="This group's invoice tries this card first, before falling back to your general methods. General is available to every scope."
			/>
		</template>
	</Dialog>
</template>
