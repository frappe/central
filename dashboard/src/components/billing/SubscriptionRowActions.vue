<script setup lang="ts">
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { SubscriptionRow } from '@/types/billing'

// The lifecycle menu for one subscription row — mirrors ServerRowActions. Which
// actions show is gated by capability and the subscription's paused state. The
// component is presentational: it emits the chosen verb; the page owns the calls.
const props = defineProps<{
	subscription: SubscriptionRow
	canManage: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	open: [sub: SubscriptionRow]
	pause: [sub: SubscriptionRow]
	resume: [sub: SubscriptionRow]
}>()

interface ActionItem {
	label: string
	icon: string
	onClick: () => void
}

const options = computed(() => {
	const items: ActionItem[] = []
	if (props.subscription.gateway_url)
		items.push({
			label: 'Open server',
			icon: 'lucide-external-link',
			onClick: () => emit('open', props.subscription),
		})
	// A terminated VM is gone — neither pause nor resume applies. Otherwise pause an
	// active subscription, or resume one whose billing is paused (server stopped).
	if (props.canManage && props.subscription.status !== 'Terminated') {
		if (props.subscription.enabled)
			items.push({
				label: 'Pause billing',
				icon: 'lucide-pause',
				onClick: () => emit('pause', props.subscription),
			})
		else
			items.push({
				label: 'Resume billing',
				icon: 'lucide-play',
				onClick: () => emit('resume', props.subscription),
			})
	}
	return items
})
</script>

<template>
	<RowActionsMenu
		:options="options"
		label="Subscription actions"
		icon="lucide-ellipsis"
		:busy="busy"
	/>
</template>
