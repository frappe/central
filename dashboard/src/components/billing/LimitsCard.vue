<script setup lang="ts">
import { Button, LoadingText } from 'frappe-ui'
import { computed, ref } from 'vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSpendingLimits } from '@/composables/useSpendingLimits'
import { money } from '@/lib/format'

defineEmits<{ openTiers: [] }>()

const {
	tier,
	currency,
	current,
	monthlySpend,
	nextLevel,
	cycleRatio,
	resourcesUsed,
	resourceRatio,
	gates,
	levels,
	reloadAfterMethodAdded,
} = useSpendingLimits()

const { complete, requireSetup } = useBillingSetup()
const { canManageBilling } = useCapabilities()

const loading = computed(() => tier.loading && !tier.data)
const nearLimit = computed(() => cycleRatio.value >= 0.8)

const showAddMethod = ref(false)

const startFirstTier = () => {
	if (requireSetup()) showAddMethod.value = true
}
</script>

<template>
	<section
		class="flex flex-wrap overflow-hidden rounded-6 border border-outline-gray-1 bg-surface-base"
	>
		<div class="flex min-w-0 flex-[1_1_18rem] flex-col gap-4 p-4">
			<div class="flex items-center gap-2.5">
				<h2 class="text-base-semibold text-ink-gray-8">Limits</h2>
				<span
					v-if="current"
					class="rounded-3 bg-surface-gray-2 px-2 py-px text-xs-medium text-ink-gray-8"
				>
					{{ current.tier }}
					tier
				</span>
			</div>

			<LoadingText v-if="loading" :lines="2" />

			<div v-else-if="!current" class="flex flex-col items-start gap-3">
				<p class="text-p-sm text-ink-gray-6">
					Add a payment method to start on the
					{{ levels[0]?.tier }}
					tier. You only pay for what you use, and your limit rises as your
					payment history grows.
				</p>
				<Button
					v-if="canManageBilling"
					variant="solid"
					:label="complete ? 'Add payment method' : 'Add billing details'"
					@click="startFirstTier"
				/>
			</div>

			<div
				v-else
				class="grid auto-cols-fr grid-flow-col grid-rows-3 gap-x-4 gap-y-1"
			>
				<span class="text-sm text-ink-gray-5">Spend per cycle</span>

				<span class="text-base-medium tabular-nums">
					<span :class="nearLimit ? 'text-ink-amber-6' : 'text-ink-gray-9'">
						{{ money(monthlySpend ?? 0, currency, { trimTrailingZeros: true }) }}
					</span>
					<span class="text-ink-gray-5">
						of
						{{ money(current.max_spend, currency, { trimTrailingZeros: true }) }}
					</span>
				</span>

				<div class="mt-1 h-1 overflow-hidden rounded-1 bg-surface-gray-2">
					<div
						class="h-full"
						:class="nearLimit ? 'bg-surface-amber-5' : 'bg-surface-gray-10'"
						:style="{ width: `${cycleRatio * 100}%` }"
					/>
				</div>

				<template v-if="current.max_resource_count != null">
					<span class="text-sm text-ink-gray-5">Resources</span>

					<span class="text-base-medium tabular-nums text-ink-gray-9">
						{{ resourcesUsed }}
						<span class="text-ink-gray-5"
							>of {{ current.max_resource_count }}</span
						>
					</span>

					<div class="mt-1 h-1 overflow-hidden rounded-1 bg-surface-gray-2">
						<div
							class="h-full bg-surface-gray-10"
							:style="{ width: `${resourceRatio * 100}%` }"
						/>
					</div>
				</template>
			</div>
		</div>

		<div
			v-if="current"
			class="-ml-px -mt-px flex min-w-0 flex-[1_1_18rem] flex-col gap-4 border-l border-t border-outline-gray-1 p-4"
		>
			<div class="flex items-center justify-between gap-2.5">
				<p v-if="nextLevel" class="text-sm text-ink-gray-6">
					Upgrade to
					<span class="text-sm-medium text-ink-gray-8"
						>{{ nextLevel.tier }}</span
					>
				</p>
				<p v-else class="text-sm text-ink-gray-6">You're on the highest tier</p>
				<Button
					class="-my-1.5"
					size="xs"
					label="Tiers"
					icon-right="lucide-panel-right-open"
					@click="$emit('openTiers')"
				/>
			</div>

			<div
				v-if="gates.length"
				class="grid auto-cols-fr grid-flow-col grid-rows-3 gap-x-4 gap-y-1"
			>
				<template v-for="gate in gates" :key="gate.label">
					<span class="text-sm text-ink-gray-5">{{ gate.label }}</span>

					<span
						class="flex items-center gap-1.5 text-base-medium tabular-nums text-ink-gray-9"
					>
						<span>
							{{ gate.have }}
							<span class="text-ink-gray-5">of {{ gate.need }}</span>
						</span>
						<span
							v-if="gate.done"
							class="lucide-check size-3.5 text-ink-green-6"
							aria-label="Met"
						/>
					</span>

					<div class="mt-1 h-1 overflow-hidden rounded-1 bg-surface-gray-2">
						<div
							class="h-full bg-surface-gray-10"
							:style="{ width: `${gate.ratio * 100}%` }"
						/>
					</div>
				</template>
			</div>
		</div>
	</section>

	<AddMethodDialog v-model="showAddMethod" @done="reloadAfterMethodAdded" />
</template>
