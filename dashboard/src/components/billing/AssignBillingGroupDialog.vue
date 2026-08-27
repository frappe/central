<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { errorToast } from '@/lib/toast'
import type { SubscriptionRow } from '@/types/billing'

// Tag a subscription into a Billing Group, or clear it back onto the team's
// consolidated invoice. Controlled by the card: pass the pending subscription
// (or null) via v-model:subscription, like PauseBillingDialog. Only the team's
// currently-enabled groups are offered — a disabled one refuses new tags
// server-side too (Subscription.validate_billing_group).
const CONSOLIDATED = ''

const props = defineProps<{ subscription: SubscriptionRow | null }>()
const emit = defineEmits<{
	'update:subscription': [sub: SubscriptionRow | null]
	assigned: []
}>()

const { groups } = useBillingOverview()

const open = computed({
	get: () => !!props.subscription,
	set: (v: boolean) => {
		if (!v) emit('update:subscription', null)
	},
})

const selected = ref(CONSOLIDATED)
watch(
	() => props.subscription,
	(sub) => {
		if (sub) selected.value = sub.billing_group || CONSOLIDATED
	},
)

const options = computed(() => [
	{ label: 'Consolidated (no group)', value: CONSOLIDATED },
	...(groups.data ?? [])
		.filter((g) => g.enabled)
		.map((g) => ({ label: g.title, value: g.name })),
])

const canSubmit = computed(
	() => selected.value !== (props.subscription?.billing_group || CONSOLIDATED),
)

const assign = useCall<unknown, { subscription: string; billing_group: string | null }>({
	url: method(API.setSubscriptionBillingGroup),
	method: 'POST',
	immediate: false,
})

async function submit(): Promise<void> {
	if (!props.subscription || !canSubmit.value) return
	try {
		await assign.submit({
			subscription: props.subscription.name,
			billing_group: selected.value || null,
		})
		if (assign.error) throw assign.error
		emit('update:subscription', null)
		emit('assigned')
	} catch (e) {
		errorToast(e)
	}
}

const dialogOptions = computed(() => ({
	title: 'Move to billing group',
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
				description="Which invoice this subscription bills on. Consolidated is your default invoice."
			/>
		</template>
	</Dialog>
</template>
