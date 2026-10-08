<script setup lang="ts">
import { Spinner, Tooltip } from 'frappe-ui'
import { NumberCard } from 'frappe-ui/charts'
import { computed } from 'vue'
import { useAI } from '@/composables/useAI'
import { formatDateTime } from '@/lib/datetime'

const { ai, aiLoading } = useAI()

const usage = computed(() => ai.value?.usage ?? null)
const balance = computed(() => ai.value?.balance ?? null)
// A free team is never charged: the balance card says so instead of hinting at caps.
const prepaid = computed(() => !!balance.value && !balance.value.is_free_user)

// A model call often costs a fraction of a cent, so small amounts keep 4 places.
const usdPrecision = (value: number): number => (value > 0 && value < 1 ? 4 : 2)
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl px-6 pb-8 pt-5">
			<div v-if="aiLoading && !ai" class="flex justify-center py-16">
				<Spinner class="size-5 text-ink-gray-5" />
			</div>

			<template v-else>
				<h2 class="text-base font-semibold text-ink-gray-8">This month</h2>

				<p class="mt-0.5 text-p-sm text-ink-gray-5">
					Across every key of the team, as of
					{{ usage?.as_of ? formatDateTime(usage.as_of) : 'the last count' }}.
				</p>

				<div class="mt-3 grid grid-cols-2 gap-4 md:grid-cols-4">
					<NumberCard
						title="Balance"
						:value="balance?.balance ?? null"
						prefix="$"
						:precision="usdPrecision(balance?.balance ?? 0)"
					>
						<template #actions>
							<Tooltip
								:text="
									prepaid
										? `$${(balance?.unallocated ?? 0).toFixed(2)} not yet handed to any key's cap. Raise a key's cap on the API keys tab to spend it.`
										: 'This is a free team: usage is counted but never charged.'
								"
							>
								<lucide-circle-help
									class="size-4 text-ink-gray-5"
									aria-label="What the balance is for"
								/>
							</Tooltip>
						</template>
					</NumberCard>
					<NumberCard
						title="Spent"
						:value="usage?.cost ?? null"
						prefix="$"
						:precision="usdPrecision(usage?.cost ?? 0)"
					/>
					<NumberCard title="Requests" :value="usage?.requests ?? null" />
					<NumberCard title="Tokens" :value="usage?.tokens ?? null">
						<template #actions>
							<Tooltip
								text="Prompt and completion tokens together, across every model and key."
							>
								<lucide-circle-help
									class="size-4 text-ink-gray-5"
									aria-label="What counts as a token"
								/>
							</Tooltip>
						</template>
					</NumberCard>
				</div>

				<p class="mt-6 text-p-sm text-ink-gray-5">
					Each key works in one geography, with its own cap, rate limits and
					models. See the API keys tab.
				</p>
			</template>
		</div>
	</div>
</template>
