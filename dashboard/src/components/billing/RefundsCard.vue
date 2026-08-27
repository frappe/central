<script setup lang="ts">
import { Badge, Button, LoadingText, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { formatDate, money } from '@/lib/format'
import type { RefundRow } from '@/types/billing'

const { activeTeam } = useSession()

const LIMIT = 1000
const PAGE = 100
const refunds = useCall<RefundRow[], { team: string; limit: number }>({
	url: method(API.refunds),
	params: () => ({ team: activeTeam.value!, limit: LIMIT }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => refunds.reload())

const loading = computed(() => refunds.loading && !refunds.data)
const rows = computed(() => refunds.data ?? [])
const truncated = computed(() => rows.value.length >= LIMIT)
const shown = ref(PAGE)
const visible = computed(() => rows.value.slice(0, shown.value))
const description = computed(() =>
	truncated.value
		? `The most recent ${LIMIT.toLocaleString()} refunds on this account.`
		: 'Every refund on this account.',
)

const STATUS_THEME: Record<string, string> = {
	Completed: 'green',
	Initiated: 'blue',
	Failed: 'red',
}
function destinationLabel(row: RefundRow): string {
	return row.destination === 'Wallet'
		? 'Returned to your wallet'
		: 'Returned to your payment method'
}
</script>

<template>
	<BillingCard
		v-if="loading || rows.length"
		title="Refunds"
		:description="description"
	>
		<LoadingText v-if="loading" :lines="2" />

		<ul v-else class="divide-y divide-outline-gray-1">
			<li v-for="row in visible" :key="row.name" class="py-3 first:pt-0">
				<div class="grid grid-cols-[1fr_5rem_7rem] items-center gap-3">
					<span class="text-base-medium tabular-nums text-ink-gray-9">
						{{ money(row.amount, row.currency) }}
					</span>
					<span class="flex justify-end">
						<Badge
							:theme="(STATUS_THEME[row.status] as any) || 'gray'"
							variant="subtle"
							:label="row.status"
						/>
					</span>
					<span class="text-right text-p-sm text-ink-gray-5">
						{{ formatDate(row.completed_at || row.created_at) }}
					</span>
				</div>
				<p class="mt-1 text-p-sm text-ink-gray-7">
					{{ destinationLabel(row) }}
					<template v-if="row.reason"> — {{ row.reason }}</template>
				</p>
				<p
					v-if="row.gateway_reference"
					class="mt-0.5 truncate font-mono text-xs text-ink-gray-4"
				>
					{{ row.gateway_reference }}
				</p>
			</li>
			<li v-if="rows.length > shown" class="py-3">
				<Button
					variant="ghost"
					size="sm"
					class="-ml-2"
					:label="`Show all ${rows.length}`"
					@click="shown = rows.length"
				/>
			</li>
		</ul>
	</BillingCard>
</template>
