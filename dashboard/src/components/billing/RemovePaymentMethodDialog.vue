<script setup lang="ts">
import { Dialog } from 'frappe-ui'
import { computed } from 'vue'
import type { PaymentMethod } from '@/types/billing'

// Confirm for removing a payment method. Controlled by the card: pass the pending
// method (or null) via v-model:method. A local Dialog (like PauseBillingDialog),
// not confirmDialog, since this app mounts no global <Dialogs /> container.
const props = defineProps<{
	method: PaymentMethod | null
	loading?: boolean
}>()

const emit = defineEmits<{
	'update:method': [pm: PaymentMethod | null]
	confirm: [pm: PaymentMethod]
}>()

const open = computed({
	get: () => !!props.method,
	set: (v: boolean) => {
		if (!v) emit('update:method', null)
	},
})

const label = computed(
	() => props.method?.display_label || props.method?.name || '',
)

const dialogOptions = computed(() => ({
	title: 'Remove payment method',
	message: `Remove ${label.value}? Invoices will fall back to your other methods, if any.`,
	actions: [
		{
			label: 'Remove',
			variant: 'solid' as const,
			theme: 'red' as const,
			loading: props.loading,
			onClick: () => {
				if (props.method) emit('confirm', props.method)
			},
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:message="dialogOptions.message"
		:actions="dialogOptions.actions"
	/>
</template>
