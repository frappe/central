<script setup lang="ts">
import { LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { formatDate, money } from '@/lib/format'

// The tray behind "Your prices are locked": every running rate against what the
// same thing would cost if provisioned today, and when each rate was struck.
//
// Rows where the catalog has since fallen BELOW the locked rate are shown too.
// Hiding them would make this a marketing surface rather than a record — the
// customer is paying over list and is entitled to know, since re-locking is a
// choice they can make.
const open = defineModel<boolean>('open', { default: false })
const { lockedPrices, currency } = useBillingOverview()

const loading = computed(() => lockedPrices.loading && !lockedPrices.data)
const data = computed(() => lockedPrices.data)
const rows = computed(() => data.value?.rows ?? [])
</script>

<template>
	<SidePanel
		v-model:open="open"
		title="Locked prices"
		:subtitle="
      data?.protected_count
        ? `Saving ${money(data.monthly_saving, currency)} a month`
        : undefined
    "
	>
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="4" />
		</div>

		<div v-else-if="!rows.length" class="px-4 py-12 text-center text-p-sm text-ink-gray-5">
			Nothing is running on a locked rate yet.
		</div>

		<template v-else>
			<ul class="divide-y divide-outline-gray-1">
				<li v-for="row in rows" :key="row.subscription" class="px-4 py-3">
					<div class="flex items-start justify-between gap-3">
						<div class="min-w-0">
							<div class="truncate text-base-medium text-ink-gray-9">
								{{ row.title }}
							</div>
							<div class="mt-0.5 text-p-sm text-ink-gray-5">
								<template v-if="row.cluster">{{ row.cluster }} · </template>
								<template v-if="row.locked_at">
									locked {{ formatDate(row.locked_at) }}
								</template>
								<template v-else>at list</template>
							</div>
						</div>
						<div class="shrink-0 text-right">
							<!-- Strike the list price only where it is genuinely higher; a
							     struck-through number that is LOWER reads as a discount we
							     are not giving. -->
							<span
								v-if="row.saving > 0 && row.list_rate != null"
								class="mr-1.5 text-p-sm tabular-nums text-ink-gray-4 line-through"
							>
								{{ money(row.list_rate, currency) }}
							</span>
							<span class="text-sm-medium tabular-nums text-ink-gray-9">
								{{ money(row.locked_rate, currency) }}
							</span>
						</div>
					</div>

					<p
						v-if="row.saving > 0"
						class="mt-1 text-p-sm text-ink-green-3"
					>
						{{ money(row.saving, currency) }} a month below today's price
					</p>
					<p
						v-else-if="row.above_list"
						class="mt-1 text-p-sm text-ink-gray-6"
					>
						{{ money(row.above_list_by, currency) }} a month above today's price
						— this plan has come down since you started.
					</p>
				</li>
			</ul>

			<div class="border-t border-outline-gray-2 p-4">
				<p v-if="data?.protected_count" class="text-p-sm text-ink-gray-5">
					Your rate is fixed at what it was when each server started. Catalog
					price rises don't reach you — that's worth
					{{ money(data.annual_saving, currency) }} a year at current prices.
				</p>
				<p v-else class="text-p-sm text-ink-gray-5">
					Your rate is fixed at what it was when each server started, so price
					rises don't reach you. Where a plan has since come down, resizing to it
					re-locks at the newer rate.
				</p>
			</div>
		</template>
	</SidePanel>
</template>
