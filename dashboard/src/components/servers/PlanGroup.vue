<script setup lang="ts">
import { computed } from 'vue'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { configSpecs, estimateConfig } from '@/lib/composed'
import { money } from '@/lib/format'
import { planPrice, planSpecs } from '@/lib/plans'
import type {
	Capacity,
	ComposedConfig,
	Plan,
	Profile,
	RateCard,
} from '@/types/api'

// One optimisation profile's slice of the plan picker: its preset rows plus a
// "Custom" row that designs a config within *this* profile (#84). Used flat (a
// region with no sub-classification) and inside a tab (one per sub-category) — the
// custom designer inherits the profile, so there's no separate profile picker.
const props = defineProps<{
	presets: Plan[]
	profile: Profile | null
	rateCard: RateCard
	available: number
	currency: string
	// The region's live capacity — passed through to cap the custom designer's sliders.
	capacity?: Capacity | null
	// Pre-fill the custom designer with a running config's shape (resize, #82/#84).
	initial?: ComposedConfig | null
}>()

const selectedPlan = defineModel<string | null>('selectedPlan', {
	required: true,
})
const composedConfig = defineModel<ComposedConfig | null>('composedConfig', {
	required: true,
})

// A profile-scoped key so the custom selection is distinct per tab.
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
const customSpec = computed<string>(() =>
	composedConfig.value
		? configSpecs(composedConfig.value, props.rateCard.Disk?.unit)
		: '',
)
const customPrice = computed<string>(() =>
	customEstimate.value !== null
		? `${money(customEstimate.value, props.currency)} / mo`
		: '',
)

// Bundle-discount note: shown only while the designed shape sits exactly on one of
// this profile's presets (which may price it below its component sum).
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
	<div class="space-y-1.5">
		<!-- Presets in this profile — one compact row each: name · specs · price. -->
		<label
			v-for="plan in presets"
			:key="plan.plan"
			:class="
				[
					'flex cursor-pointer items-center gap-3 rounded-6 border px-3 py-2 text-sm',
					'transition-colors',
					'focus-within:border-outline-gray-4 focus-within:ring-1 focus-within:ring-outline-gray-4',
					selectedPlan === plan.plan
						? 'border-outline-gray-4 bg-surface-gray-1'
						: 'border-outline-gray-2 hover:border-outline-gray-3',
				]
			"
		>
			<input
				v-model="selectedPlan"
				type="radio"
				:value="plan.plan"
				class="peer sr-only"
			/>
			<span
				aria-hidden="true"
				class="size-3.5 shrink-0 rounded-full border border-outline-gray-4 peer-checked:border-4 peer-checked:border-outline-gray-5"
			/>
			<!-- Title carries the size too (e.g. "Starter · 1 vCPU / 2 GB"); the specs
           already spell it out, so show just the tier name to avoid the echo. -->
			<span class="shrink-0 font-medium text-ink-gray-9"
				>{{ plan.title.split(' · ')[0] }}</span
			>
			<span class="min-w-0 flex-1 truncate text-ink-gray-5"
				>{{ planSpecs(plan) }}</span
			>
			<span class="shrink-0 font-medium text-ink-gray-9"
				>{{ planPrice(plan) }}</span
			>
		</label>

		<!-- Custom: a radio row that expands into the design slider for this profile. -->
		<div
			v-if="profile"
			:class="
				[
					'rounded-6 border transition-colors',
					'focus-within:border-outline-gray-4 focus-within:ring-1 focus-within:ring-outline-gray-4',
					isCustom
						? 'border-outline-gray-4 bg-surface-gray-1'
						: 'border-outline-gray-2 hover:border-outline-gray-3',
				]
			"
		>
			<label class="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm">
				<input
					v-model="selectedPlan"
					type="radio"
					:value="customKey"
					class="peer sr-only"
				/>
				<span
					aria-hidden="true"
					class="size-3.5 shrink-0 rounded-full border border-outline-gray-4 peer-checked:border-4 peer-checked:border-outline-gray-5"
				/>
				<span
					class="flex shrink-0 items-center gap-1.5 font-medium text-ink-gray-9"
				>
					Custom
					<span
						class="lucide-sliders-horizontal size-3.5 text-ink-gray-5"
						aria-hidden="true"
					/>
				</span>
				<span class="min-w-0 flex-1 truncate text-ink-gray-5"
					>{{ isCustom ? customSpec : '' }}</span
				>
				<span class="shrink-0 font-medium text-ink-gray-9"
					>{{ isCustom ? customPrice : 'Design your own' }}</span
				>
			</label>

			<!-- Smooth expand: animate grid rows 0fr → 1fr (CSS only). -->
			<div
				class="grid transition-[grid-template-rows] duration-200 ease-out"
				:class="isCustom ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
			>
				<div class="overflow-hidden">
					<div class="border-t border-outline-gray-2 px-4 py-4">
						<ConfigDesigner
							v-if="isCustom"
							:key="profile.sub_category"
							v-model="composedConfig"
							:profiles="[profile]"
							:rate-card="rateCard"
							:available="available"
							:capacity="capacity"
							:initial="initial"
						/>
						<p v-if="matchingPreset" class="mt-3 text-p-xs text-ink-gray-5">
							The
							<span class="font-medium text-ink-gray-7"
								>{{ matchingPreset.title }}</span
							>
							preset offers this exact shape — it may be cheaper than building
							it à la carte.
						</p>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
