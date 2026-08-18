<script setup lang="ts">
import { Badge, Button, LoadingText } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { ordinal } from '@/lib/date'
import { formatDate, money, plural } from '@/lib/format'
import { paymentAttemptDisplay } from '@/lib/status'
import type { PaymentAttempt } from '@/types/billing'

const props = defineProps<{
	attempts: PaymentAttempt[] | null
	loading: boolean
	exportUrl: string
}>()
const open = defineModel<boolean>('open', { default: false })

const rows = computed(() => props.attempts ?? [])

const PAGE = 100
const shown = ref(PAGE)
watch(open, (isOpen) => {
	if (isOpen) shown.value = PAGE
})
const visible = computed(() => rows.value.slice(0, shown.value))
</script>

<template>
	<SidePanel
		v-model:open="open"
		title="Payments"
		:subtitle="rows.length ? plural(rows.length, 'attempt') : undefined"
	>
		<template #actions>
			<Button variant="ghost" size="sm" :link="props.exportUrl" label="Export">
				<template #prefix>
					<span class="lucide-download size-4" aria-hidden="true" />
				</template>
			</Button>
		</template>
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>
		<ul v-else class="divide-y divide-outline-gray-1">
			<li v-for="row in visible" :key="row.name" class="px-4 py-3">
				<div class="grid grid-cols-[1fr_auto] items-start gap-3">
					<span class="flex min-w-0 items-baseline gap-2">
						<span class="text-base-medium tabular-nums text-ink-gray-9">
							{{ money(row.amount, row.currency) }}
						</span>
						<span v-if="row.retry_number" class="shrink-0 text-p-sm text-ink-gray-4">
							{{ ordinal(row.retry_number) }} retry
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
				<p v-if="row.reason" class="mt-1 text-p-sm text-ink-gray-7">{{ row.reason }}</p>
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
			<li v-if="rows.length > shown" class="px-4 py-3">
				<Button
					variant="ghost"
					size="sm"
					:label="`Show all ${rows.length}`"
					@click="shown = rows.length"
				/>
			</li>
		</ul>
	</SidePanel>
</template>
