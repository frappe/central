<script setup lang="ts">
import { Badge, LoadingText, useCall } from 'frappe-ui'
import { computed, watch } from 'vue'
import { API, method } from '@/api/methods'
import SidePanel from '@/components/common/SidePanel.vue'
import { useSession } from '@/composables/useSession'
import { formatDate, money } from '@/lib/format'
import type { PaymentAttempt } from '@/types/billing'

// Every charge against the team, in full. Loaded when the tray opens — nobody
// needs a year of attempts on first paint.
const open = defineModel<boolean>('open', { default: false })
const { activeTeam } = useSession()

const attempts = useCall<PaymentAttempt[], { team: string }>({
	url: method(API.paymentAttempts),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
})
watch(open, (isOpen) => {
	if (isOpen && activeTeam.value) attempts.reload()
})

const loading = computed(() => attempts.loading && !attempts.data)
const rows = computed(() => attempts.data ?? [])

const STATUS: Record<string, { label: string; theme: string }> = {
	Captured: { label: 'Paid', theme: 'green' },
	Authorised: { label: 'Authorised', theme: 'blue' },
	Initiated: { label: 'Processing', theme: 'blue' },
	Failed: { label: 'Failed', theme: 'red' },
	Refunded: { label: 'Refunded', theme: 'gray' },
}
const badge = (row: PaymentAttempt) => STATUS[row.status] || { label: row.status, theme: 'gray' }
</script>

<template>
	<SidePanel
		v-model:open="open"
		title="Payments"
		:subtitle="rows.length ? `${rows.length} attempts` : undefined"
	>
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>
		<ul v-else class="divide-y divide-outline-gray-1">
			<li v-for="row in rows" :key="row.name" class="px-4 py-3">
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="text-base-medium tabular-nums text-ink-gray-9">
								{{ money(row.amount, row.currency) }}
							</span>
							<Badge :theme="(badge(row).theme as any)" :label="badge(row).label" />
							<span v-if="row.retry_number" class="text-p-sm text-ink-gray-4">
								retry {{ row.retry_number }}
							</span>
						</div>
						<p v-if="row.reason" class="mt-0.5 text-p-sm text-ink-gray-7">
							{{ row.reason }}
						</p>
					</div>
					<div class="shrink-0 text-right">
						<p class="text-p-sm text-ink-gray-5">{{ formatDate(row.creation) }}</p>
						<p
							v-if="row.gateway_transaction_id"
							class="mt-0.5 font-mono text-xs text-ink-gray-4"
						>
							{{ row.gateway_transaction_id }}
						</p>
					</div>
				</div>
			</li>
		</ul>
	</SidePanel>
</template>
