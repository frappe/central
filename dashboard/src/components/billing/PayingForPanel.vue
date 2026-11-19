<script setup lang="ts">
import { LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import PayingForTable from '@/components/billing/PayingForTable.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayingFor } from '@/composables/usePayingFor'
import { money } from '@/lib/format'

const open = defineModel<boolean>('open', { default: false })
const { canManageBilling } = useCapabilities()
const {
	rows,
	loading,
	currency,
	total,
	busy,
	openServer,
	askPause,
	onResume,
	askAssignProject,
} = usePayingFor()

const subtitle = computed(() =>
	rows.value.length
		? `${rows.value.length} item${rows.value.length === 1 ? '' : 's'} · ${money(total.value, currency.value)} so far`
		: undefined,
)
</script>

<template>
	<SidePanel v-model:open="open" title="Subscriptions" :subtitle="subtitle">
		<LoadingText v-if="loading" :lines="6" class="p-4" />
		<PayingForTable
			v-else
			hide-header
			:rows="rows"
			:currency="currency"
			:can-manage="canManageBilling"
			:busy="busy"
			@open="openServer"
			@pause="askPause"
			@resume="onResume"
			@assign-project="askAssignProject"
		/>
	</SidePanel>
</template>
