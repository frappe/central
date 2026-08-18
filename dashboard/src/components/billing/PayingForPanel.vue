<script setup lang="ts">
import { LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import PayingForRow from '@/components/billing/PayingForRow.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { usePayingFor } from '@/composables/usePayingFor'
import { money } from '@/lib/format'

// Everything being billed this cycle, in full. The card keeps the top few; this
// is where the long tail goes, so the card never grows its own scrollbar.
const open = defineModel<boolean>('open', { default: false })
const { rows, loading, currency, total, openServer } = usePayingFor()

const subtitle = computed(() =>
	rows.value.length
		? `${rows.value.length} item${rows.value.length === 1 ? '' : 's'} · ${money(total.value, currency.value)} so far`
		: undefined,
)
</script>

<template>
	<SidePanel v-model:open="open" title="Subscriptions" :subtitle="subtitle">
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>
		<div v-else class="divide-y divide-outline-gray-1 px-4">
			<PayingForRow
				v-for="row in rows"
				:key="row.id"
				:row="row"
				:currency="currency"
				@open="openServer"
			/>
		</div>
	</SidePanel>
</template>
