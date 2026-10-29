<script setup lang="ts">
import { LoadingText } from 'frappe-ui'
import ContactSupportLink from '@/components/common/ContactSupportLink.vue'
import SideSheet from '@/components/common/SideSheet.vue'
import { useSpendingLimits } from '@/composables/useSpendingLimits'
import { money } from '@/lib/format'
import type { TierLevel } from '@/types/billing'

const open = defineModel<boolean>('open', { default: false })

const { tier, currency, levels, nextLevel, record, requirementsFor } =
	useSpendingLimits()

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
			<table class="w-full border-collapse text-base">
				<thead>
					<tr class="text-left text-sm text-ink-gray-5">
						<th class="px-5 py-3">Tier</th>
						<th class="px-2 py-3">To qualify</th>
						<th class="px-5 py-3 text-right">Limit</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-outline-gray-1">
					<tr
						v-for="level in levels"
						:key="level.tier"
						class="align-top"
						:class="level.state === 'current' ? 'bg-surface-gray-2' : ''"
					>
						<td class="px-5 py-3.5">
							<div class="flex items-center gap-2">
								<span
									:class="
										level.state === 'reached'
											? 'text-ink-gray-5'
											: 'text-base-medium text-ink-gray-9'
									"
								>
									{{ level.tier }}
								</span>
								<span
									v-if="level.state === 'current'"
									class="rounded-2 bg-surface-gray-9 px-1.5 py-0.5 text-xs-medium text-ink-base"
								>
									Current
								</span>
								<span
									v-else-if="level.tier === nextLevel?.tier"
									class="rounded-2 border border-outline-blue-3 px-1.5 py-px text-xs-medium text-ink-blue-6"
								>
									Next
								</span>
							</div>
						</td>
						<td
							class="px-2 py-3.5"
							:class="
								level.state === 'reached' ? 'text-ink-gray-5' : 'text-ink-gray-7'
							"
						>
							{{ requirementText(level) }}
						</td>
						<td class="px-5 py-3.5 text-right">
							<div
								class="whitespace-nowrap tabular-nums"
								:class="
									level.state === 'reached'
										? 'text-ink-gray-5'
										: 'text-base-medium text-ink-gray-9'
								"
							>
								{{ money(level.max_spend, currency, { trimTrailingZeros: true }) }}
							</div>
							<div
								v-if="level.max_resource_count != null"
								class="mt-0.5 whitespace-nowrap text-sm tabular-nums text-ink-gray-5"
							>
								{{ level.max_resource_count }}
								resource{{ level.max_resource_count === 1 ? '' : 's' }}
							</div>
						</td>
					</tr>
				</tbody>
			</table>

			<div class="flex flex-col gap-2 p-5 text-p-sm text-ink-gray-5">
				<p>
					<span class="text-ink-gray-8">Resource</span>
					— anything that bills while it runs: a server or a subscribed service.
				</p>
				<p>
					<span class="text-ink-gray-8">Limit</span>
					— the most your team can spend in one billing cycle.
				</p>
				<p v-if="record">{{ record }}</p>
				<p>
					Need a higher limit now?
					<ContactSupportLink :context="{ Topic: 'Need higher spending limit' }"
						>Contact support</ContactSupportLink
					>.
				</p>
			</div>
		</template>
	</SideSheet>
</template>
