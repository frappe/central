<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { computed } from 'vue'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { configSpecs, estimateConfig } from '@/lib/composed'
import { money } from '@/lib/format'
import { planSpecs } from '@/lib/plans'
import type {
	Capacity,
	ComposedConfig,
	Plan,
	Profile,
	RateCard,
} from '@/types/api'

const props = defineProps<{
	presets: Plan[]
	profile: Profile | null
	rateCard: RateCard
	available: number
	currency: string
	capacity?: Capacity | null
	initial?: ComposedConfig | null
	omitDisk?: boolean
	currentPlan?: string | null
	minDisk?: number
}>()

const selectedPlan = defineModel<string | null>('selectedPlan', {
	required: true,
})
const composedConfig = defineModel<ComposedConfig | null>('composedConfig', {
	required: true,
})

const customKey = computed(() =>
	props.profile ? `custom:${props.profile.sub_category}` : '',
)
const isCustom = computed(
	() => !!props.profile && selectedPlan.value === customKey.value,
)

const customEstimate = computed<number | null>(() =>
	composedConfig.value
		? estimateConfig(composedConfig.value, props.rateCard)
		: null,
)
const customSpec = computed<string>(() => {
	const config = composedConfig.value
	if (!config) return ''
	if (!props.omitDisk) return configSpecs(config, props.rateCard.Disk?.unit)
	return `${config.vcpus} vCPU · ${config.memory_gb} GB RAM`
})

function bundledDisk(plan: Plan): number {
	return (
		plan.includes.find((inc) => inc.resource_type === 'Disk')?.quantity ?? 0
	)
}
function diskTooSmall(plan: Plan): boolean {
	return props.minDisk != null && bundledDisk(plan) < props.minDisk
}

const matchingPreset = computed<Plan | null>(() => {
	const c = composedConfig.value
	if (!c || !isCustom.value) return null
	const qty = (p: Plan, t: string) =>
		p.includes.find((i) => i.resource_type === t)?.quantity ?? 0
	return (
		props.presets.find(
			(p) =>
				qty(p, 'Compute') === c.vcpus &&
				qty(p, 'Memory') === c.memory_gb &&
				qty(p, 'Disk') === c.disk_gb,
		) ?? null
	)
})
</script>

<template>
	<div class="space-y-3">
		<div class="grid grid-cols-2 gap-3 md:grid-cols-3">
			<button
				v-for="plan in presets"
				:key="plan.plan"
				type="button"
				:aria-pressed="selectedPlan === plan.plan"
				:disabled="diskTooSmall(plan)"
				class="flex flex-col rounded-6 border border-outline-gray-2 p-4 text-start transition-colors hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-outline-gray-4 disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:border-outline-gray-6"
				@click="selectedPlan = plan.plan"
			>
				<span class="flex items-center justify-between gap-2">
					<span class="truncate text-sm-medium text-ink-gray-7">{{
						plan.title.split(' · ')[0]
					}}</span>
					<Badge
						v-if="currentPlan === plan.plan"
						label="Current"
						theme="gray"
						variant="subtle"
						size="sm"
					/>
				</span>
				<span class="mt-2 block text-2xl-semibold text-ink-gray-9">
					{{ money(plan.rate, plan.currency, { trimTrailingZeros: true }) }}
					<span class="text-sm text-ink-gray-5">{{
						plan.billing_cycle === 'Annual' ? '/yr' : '/mo'
					}}</span>
				</span>
				<span
					class="mt-2 block text-p-sm text-ink-gray-5"
				>
					{{ planSpecs(plan, { disk: !omitDisk }) }}
				</span>
			</button>

			<button
				v-if="profile"
				type="button"
				:aria-pressed="isCustom"
				class="col-span-2 flex items-center gap-4 rounded-6 border border-outline-gray-2 p-4 text-start transition-colors hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-outline-gray-4 aria-pressed:border-outline-gray-6"
				@click="selectedPlan = customKey"
			>
				<span
					class="grid size-10 shrink-0 place-items-center rounded-6 bg-surface-gray-3"
					aria-hidden="true"
				>
					<span class="lucide-sliders-horizontal size-5 text-ink-gray-7" />
				</span>
				<span class="min-w-0 space-y-2">
					<span class="block text-sm-medium text-ink-gray-7">Custom</span>
					<span
						v-if="isCustom && customEstimate !== null"
						class="block text-2xl-semibold text-ink-gray-9"
					>
						{{ money(customEstimate, currency, { trimTrailingZeros: true }) }}
						<span class="text-sm text-ink-gray-5">/mo</span>
					</span>
					<span v-else class="block text-lg-semibold text-ink-gray-9">
						Build your own
					</span>
					<span class="block truncate text-sm text-ink-gray-5">{{
						isCustom && customSpec
							? customSpec
							: 'Pick exactly the vCPU, memory and disk you need'
					}}</span>
				</span>
			</button>
		</div>

		<div
			v-if="profile && isCustom"
			class="rounded-6 border border-outline-gray-2 p-4"
		>
			<ConfigDesigner
				:key="profile.sub_category"
				v-model="composedConfig"
				:profiles="[profile]"
				:rate-card="rateCard"
				:available="available"
				:capacity="capacity"
				:initial="initial"
				:hide-disk="omitDisk"
			/>
			<p v-if="matchingPreset" class="mt-3 text-p-xs text-ink-gray-5">
				The
				<span class="font-medium text-ink-gray-7">{{
					matchingPreset.title
				}}</span>
				preset offers this exact shape. It may be cheaper than building it à la
				carte.
			</p>
		</div>
	</div>
</template>
