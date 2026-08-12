<script setup lang="ts">
import { Badge, Button, LoadingText, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { formatDate, money } from '@/lib/format'
import type { PaymentAttempt } from '@/types/billing'

// Every charge against this team, across invoices — the per-invoice timeline
// covers the common case, but "why did my card get declined in April" is a
// question about the account, not about one bill.
//
// A failed row leads with plain language ("Your card has expired"), not the
// gateway's own code. The raw wording is kept underneath for anyone quoting it
// to support.
// Five is the shape of the recent record; the rest is a tray, not a scrollbar
// inside a card.
const VISIBLE = 5
defineProps<{ exportUrl: string }>()
defineEmits<{ open: [] }>()
const { activeTeam } = useSession()

const attempts = useCall<PaymentAttempt[], { team: string }>({
	url: method(API.paymentAttempts),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => attempts.reload())

const loading = computed(() => attempts.loading && !attempts.data)
const all = computed(() => attempts.data ?? [])
const rows = computed(() => all.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, all.value.length - VISIBLE))

const STATUS: Record<string, { label: string; theme: string }> = {
	Captured: { label: 'Paid', theme: 'green' },
	Authorised: { label: 'Authorised', theme: 'blue' },
	Initiated: { label: 'Processing', theme: 'blue' },
	Failed: { label: 'Failed', theme: 'red' },
	Refunded: { label: 'Refunded', theme: 'gray' },
}
function badge(row: PaymentAttempt) {
	return STATUS[row.status] || { label: row.status, theme: 'gray' }
}
</script>

<template>
	<BillingCard v-if="loading || all.length" title="Payments">
		<template v-if="all.length" #action>
			<Button variant="ghost" size="xs" :link="exportUrl" label="Export">
				<template #prefix>
					<span class="lucide-download size-3.5" aria-hidden="true" />
				</template>
			</Button>
		</template>

		<LoadingText v-if="loading" :lines="3" />

		<template v-else>
			<ul class="divide-y divide-outline-gray-1">
				<li
					v-for="row in rows"
					:key="row.name"
					class="flex items-start justify-between gap-3 py-3 first:pt-0"
				>
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="text-base-medium tabular-nums text-ink-gray-9">
								{{ money(row.amount, row.currency) }}
							</span>
							<Badge :theme="(badge(row).theme as any)" :label="badge(row).label" />
							<span
								v-if="row.retry_number"
								class="text-p-sm text-ink-gray-4"
							>
								retry {{ row.retry_number }}
							</span>
						</div>
						<!-- Plain language first; the gateway's own wording sits under it. -->
						<p v-if="row.reason" class="mt-0.5 text-p-sm text-ink-gray-7">
							{{ row.reason }}
						</p>
						<p
							v-if="row.failure_reason && row.failure_reason !== row.reason"
							class="mt-0.5 text-p-sm text-ink-gray-4"
						>
							{{ row.failure_reason }}
						</p>
					</div>
					<div class="shrink-0 text-right">
						<p class="text-p-sm text-ink-gray-5">
							{{ formatDate(row.creation) }}
						</p>
						<p
							v-if="row.gateway_transaction_id"
							class="mt-0.5 font-mono text-xs text-ink-gray-4"
						>
							{{ row.gateway_transaction_id }}
						</p>
					</div>
				</li>
			</ul>

			<Button
				v-if="hidden"
				variant="ghost"
				size="sm"
				class="-ml-2 mt-2"
				:label="`View all ${all.length}`"
				@click="$emit('open')"
			>
				<template #suffix>
					<span class="lucide-chevron-right size-4" aria-hidden="true" />
				</template>
			</Button>
		</template>
	</BillingCard>
</template>
