<script setup lang="ts">
import { LoadingText } from 'frappe-ui'
import ContactSupportLink from '@/components/common/ContactSupportLink.vue'
import SideSheet from '@/components/common/SideSheet.vue'
import Table from '@/components/common/Table.vue'
import { useSpendingLimits } from '@/composables/useSpendingLimits'
import { money } from '@/lib/format'
import type { TierLevel } from '@/types/billing'

const open = defineModel<boolean>('open', { default: false })

const { tier, currency, levels, nextLevel, record, requirementsFor } =
	useSpendingLimits()

const columns = [
	{ key: 'tier', label: 'Tier' },
	{ key: 'requirements', label: 'To qualify' },
	{ key: 'limit', label: 'Limit' },
]

type Level = (typeof levels.value)[number]

const rowClass = (level: Level) =>
	level.state === 'current' ? 'bg-surface-gray-1' : undefined

const requirementText = (level: TierLevel) =>
	requirementsFor(level)
		.map((requirement) => requirement.text)
		.join(' · ')
</script>

<template>
	<SideSheet
		v-model:open="open"
		title="Limit tiers"
		description="Tiers rise automatically as you pay invoices."
	>
		<LoadingText v-if="tier.loading && !tier.data" :lines="8" class="p-5" />

		<p v-else-if="!levels.length" class="p-5 text-p-sm text-ink-gray-5">
			Spending tiers aren't configured yet.
		</p>

		<template v-else>
			<Table flush :columns="columns" :rows="levels" :row-class="rowClass">
				<template #tier="{ row }">
					<span class="flex items-center gap-2">
						<span
							:class="
								row.state === 'reached'
									? 'text-ink-gray-5'
									: 'text-base-medium text-ink-gray-9'
							"
						>
							{{ row.tier }}
						</span>
						<span
							v-if="row.state === 'current'"
							class="rounded-2 bg-surface-gray-9 px-1.5 py-0.5 text-xs-medium text-ink-base"
						>
							Current
						</span>
						<span
							v-else-if="row.tier === nextLevel?.tier"
							class="rounded-2 border border-outline-blue-3 px-1.5 py-px text-xs-medium text-ink-blue-6"
						>
							Next
						</span>
					</span>
				</template>

				<template #requirements="{ row }">
					<span
						:class="row.state === 'reached' ? 'text-ink-gray-5' : 'text-ink-gray-7'"
					>
						{{ requirementText(row) }}
					</span>
				</template>

				<template #limit="{ row }">
					<span
						class="block py-2 tabular-nums"
						:class="
							row.state === 'reached'
								? 'text-ink-gray-5'
								: 'text-base-medium text-ink-gray-9'
						"
					>
						{{ money(row.max_spend, currency, { trimTrailingZeros: true }) }}
						<span
							v-if="row.max_resource_count != null"
							class="block text-sm text-ink-gray-5"
						>
							{{ row.max_resource_count }}
							resource{{ row.max_resource_count === 1 ? '' : 's' }}
						</span>
					</span>
				</template>
			</Table>
		</template>

		<template #footer>
			<div
				class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-p-sm text-ink-gray-5"
			>
				<span class="text-ink-gray-8">Resource</span>
				<span
					>Anything that bills while it runs: a server or a subscribed service.</span
				>

				<span class="text-ink-gray-8">Limit</span>
				<span>The most your team can spend in one billing cycle.</span>

				<p v-if="record" class="col-span-2">{{ record }}</p>

				<p class="col-span-2">
					Need a higher limit now?
					<ContactSupportLink :context="{ Topic: 'Need higher spending limit' }"
						>Contact support</ContactSupportLink
					>.
				</p>
			</div>
		</template>
	</SideSheet>
</template>
