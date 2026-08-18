<script setup lang="ts">
import { Badge, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { billingPeriod } from '@/lib/date'
import { invoiceTheme } from '@/lib/status'
import { money } from '@/lib/format'
import type { Statement } from '@/types/billing'

const props = defineProps<{ statement: Statement | null; loading: boolean }>()
const open = defineModel<boolean>('open', { default: false })

const data = computed(() => props.statement)
const currency = computed(() => data.value?.currency ?? 'INR')
const rows = computed(() => [...(data.value?.rows ?? [])].reverse())
</script>

<template>
	<SidePanel
		v-model:open="open"
		title="Statement of account"
		:subtitle="data ? billingPeriod(data.from_date, data.to_date) : undefined"
	>
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>
		<ul v-else-if="data" class="divide-y divide-outline-gray-1">
			<li
				v-for="row in rows"
				:key="row.invoice"
				class="grid grid-cols-[1fr_auto] items-start gap-3 px-4 py-3"
			>
				<div class="min-w-0">
					<span class="truncate text-p-sm text-ink-gray-8">
						{{ billingPeriod(row.period_start, row.period_end) }}
					</span>
					<p v-if="row.credit_applied" class="mt-0.5 text-p-sm text-ink-gray-5">
						{{ money(row.credit_applied, currency) }} from credits
					</p>
				</div>
				<div class="flex shrink-0 items-center gap-3">
					<Badge :theme="invoiceTheme(row.status)" variant="subtle" :label="row.status" />
					<span class="w-24 text-right text-p-sm tabular-nums text-ink-gray-9">
						{{ money(row.total, currency) }}
					</span>
				</div>
			</li>
		</ul>
	</SidePanel>
</template>
