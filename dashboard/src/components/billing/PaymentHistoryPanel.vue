<script setup lang="ts">
import { Badge, LoadingText, useCall } from 'frappe-ui'
import { computed, watch } from 'vue'
import { API, method } from '@/api/methods'
import SidePanel from '@/components/common/SidePanel.vue'
import { useSession } from '@/composables/useSession'
import { formatDate, money } from '@/lib/format'
import { paymentAttemptDisplay } from '@/lib/status'
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

// Label + theme from lib/status, the same resolver the card and the Invoices list
// use.
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
				<div class="grid grid-cols-[1fr_auto] items-start gap-3">
					<span class="flex min-w-0 items-baseline gap-2">
						<span class="text-base-medium tabular-nums text-ink-gray-9">
							{{ money(row.amount, row.currency) }}
						</span>
						<span
							v-if="row.retry_number"
							class="shrink-0 text-p-sm text-ink-gray-4"
						>
							retry {{ row.retry_number }}
						</span>
					</span>
					<span class="flex shrink-0 items-center gap-3">
						<Badge
							:theme="paymentAttemptDisplay(row.status).theme"
							variant="subtle"
							:label="paymentAttemptDisplay(row.status).label"
						/>
						<span class="w-20 text-right text-p-sm text-ink-gray-5">
							{{ formatDate(row.at) }}
						</span>
					</span>
				</div>
				<p v-if="row.reason" class="mt-1 text-p-sm text-ink-gray-7">
					{{ row.reason }}
				</p>
				<!-- The gateway's own wording, kept here for anyone quoting it to support. -->
				<p
					v-if="row.failure_reason && row.failure_reason !== row.reason"
					class="mt-0.5 text-p-sm text-ink-gray-4"
				>
					{{ row.failure_reason }}
				</p>
				<p
					v-if="row.gateway_transaction_id"
					class="mt-1 truncate font-mono text-xs text-ink-gray-4"
				>
					{{ row.gateway_transaction_id }}
				</p>
			</li>
		</ul>
	</SidePanel>
</template>
