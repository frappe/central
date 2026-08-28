<script setup lang="ts">
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { PaymentMethod } from '@/types/billing'

// The menu for one payment-method row — mirrors SubscriptionRowActions. Which
// actions show is gated by capability and the row's position in the fallback
// order. Presentational: it emits the chosen verb; the card owns the calls.
const props = defineProps<{
	method: PaymentMethod
	canManage: boolean
	isFirst: boolean
	isLast: boolean
	busy?: boolean
	/** True only for the row that currently holds the title. */
	isPrimary?: boolean
	/** False while credits are paying the bill: the choice is offered, not hidden,
	 *  but it decides nothing until the balance runs out. */
	canPromote?: boolean
}>()

const emit = defineEmits<{
	makeDefault: [pm: PaymentMethod]
	moveUp: [pm: PaymentMethod]
	moveDown: [pm: PaymentMethod]
	remove: [pm: PaymentMethod]
}>()

interface ActionItem {
	label: string
	icon: string
	onClick: () => void
	disabled?: boolean
}

const options = computed(() => {
	if (!props.canManage) return []
	const items: ActionItem[] = []
	// Any row that is not the primary can become it — which is every method row
	// while the wallet holds the title.
	if (!props.isPrimary)
		items.push({
			label: 'Primary payment method',
			icon: 'lucide-star',
			disabled: props.canPromote === false,
			onClick: () => emit('makeDefault', props.method),
		})
	if (!props.isFirst)
		items.push({
			label: 'Move up',
			icon: 'lucide-arrow-up',
			onClick: () => emit('moveUp', props.method),
		})
	if (!props.isLast)
		items.push({
			label: 'Move down',
			icon: 'lucide-arrow-down',
			onClick: () => emit('moveDown', props.method),
		})
	items.push({
		label: 'Remove',
		icon: 'lucide-trash-2',
		onClick: () => emit('remove', props.method),
	})
	return items
})
</script>

<template>
	<RowActionsMenu
		:options="options"
		label="Payment method actions"
		icon="lucide-ellipsis"
		:busy="busy"
	/>
</template>
