<script setup lang="ts">
import { Badge, LoadingText, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { formatDate, money } from '@/lib/format'
import type { RefundRow } from '@/types/billing'

// Refunds raised on this team's payments. Renders nothing at all when there are
// none — an empty "Refunds" card on a healthy account is a question the customer
// didn't ask, and one they may read as a problem.
//
// The reference shown is the PROVIDER's refund id, not the bank's ARN. Wording
// stays deliberately short of "trace this with your bank": the ARN arrives on a
// dispute/refund webhook we don't route yet, and promising traceability we can't
// deliver is worse than saying less.
const { activeTeam } = useSession()

const refunds = useCall<RefundRow[], { team: string }>({
	url: method(API.refunds),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => refunds.reload())

const loading = computed(() => refunds.loading && !refunds.data)
const rows = computed(() => refunds.data ?? [])

const STATUS_THEME: Record<string, string> = {
	Completed: 'green',
	Initiated: 'blue',
	Failed: 'red',
}
function destinationLabel(row: RefundRow): string {
	return row.destination === 'Wallet'
		? 'Returned to your wallet'
		: 'Returned to your original payment method'
}
</script>

<template>
	<BillingCard v-if="loading || rows.length" title="Refunds">
		<LoadingText v-if="loading" :lines="2" />

		<ul v-else class="divide-y divide-outline-gray-1">
			<li v-for="row in rows" :key="row.name" class="py-3 first:pt-0">
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="text-base-medium text-ink-gray-9">
								{{ money(row.amount, row.currency) }}
							</span>
							<Badge
								:theme="(STATUS_THEME[row.status] as any) || 'gray'"
								:label="row.status"
							/>
						</div>
						<p class="mt-0.5 text-p-sm text-ink-gray-5">
							{{ destinationLabel(row) }}
						</p>
						<p v-if="row.reason" class="mt-0.5 text-p-sm text-ink-gray-5">
							{{ row.reason }}
						</p>
					</div>
					<div class="shrink-0 text-right">
						<p class="text-p-sm text-ink-gray-5">
							{{ formatDate(row.completed_at || row.created_at) }}
						</p>
						<p
							v-if="row.gateway_reference"
							class="mt-0.5 font-mono text-xs text-ink-gray-4"
						>
							{{ row.gateway_reference }}
						</p>
					</div>
				</div>
			</li>
		</ul>
	</BillingCard>
</template>
