<script setup lang="ts">
import { Badge, Button, LoadingText, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { formatDate, money } from '@/lib/format'
import { paymentAttemptDisplay } from '@/lib/status'
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

// Status label + theme come from lib/status, beside the invoice one, so payments
// read the same on every surface — and so the next person changing "Paid" has one
// place to change it.
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
				<!-- Amount | Status | When — the Invoices list's three columns. The badge
				     used to trail the amount, so its position moved with the figure. -->
				<li v-for="row in rows" :key="row.name" class="py-3 first:pt-0">
					<div class="grid grid-cols-[1fr_5rem_6rem] items-center gap-3">
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
						<span class="flex justify-end">
							<Badge
								:theme="paymentAttemptDisplay(row.status).theme"
								variant="subtle"
								:label="paymentAttemptDisplay(row.status).label"
							/>
						</span>
						<!-- Date only. The gateway reference does not fit this column and a
						     half-shown id is worse than none — you cannot quote it to
						     anyone. It is in the tray, in full. -->
						<span class="text-right text-p-sm text-ink-gray-5">
							{{ formatDate(row.at) }}
						</span>
					</div>
					<!-- The card carries the plain-language reason only. The gateway's own
					     wording says the same thing again in its words — that's detail, and
					     detail lives in the tray. -->
					<p v-if="row.reason" class="mt-1 text-p-sm text-ink-gray-7">
						{{ row.reason }}
					</p>
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
