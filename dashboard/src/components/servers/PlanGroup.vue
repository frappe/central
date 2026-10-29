<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { computed, nextTick } from 'vue'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { configSpecs, estimateConfig } from '@/lib/composed'
import { money } from '@/lib/format'
import {
	formatTransfer,
	planAllowances,
	planQuantity,
	planSize,
	presetPrice,
} from '@/lib/plans'
import { formatMemory, formatVcpu, gigabytesToMegabytes } from '@/lib/units'
import type {
	Capacity,
	ComposedConfig,
	Plan,
	Profile,
	RateCard,
} from '@/types/api'

interface Props {
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
	/** The running disk is the minimum for the custom designer in either resize mode. */
	currentDisk?: number
	/** Shown once under the plans, since every server includes the same transfer. */
	includedTransferGigabytes?: number
}

const props = defineProps<Props>()

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

const pickCustom = async (event: MouseEvent): Promise<void> => {
	const card = event.currentTarget as HTMLElement
	selectedPlan.value = customKey.value
	await nextTick()
	card.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const customEstimate = computed<number | null>(() =>
	composedConfig.value
		? estimateConfig(composedConfig.value, props.rateCard)
		: null,
)
const customSpec = computed<string>(() => {
	const config = composedConfig.value
	if (!config) return ''
	if (!props.omitDisk) return configSpecs(config, props.rateCard.Disk?.unit)
	return `${formatVcpu(config.vcpus)} vCPU · ${formatMemory(gigabytesToMegabytes(config.memory_gb))} RAM`
})

function diskTooSmall(plan: Plan): boolean {
	return props.minDisk != null && planQuantity(plan, 'Disk') < props.minDisk
}

function diskFor(plan: Plan): number {
	return props.omitDisk && props.currentDisk != null
		? props.currentDisk
		: planQuantity(plan, 'Disk')
}

function priceFor(plan: Plan): number | null {
	return presetPrice(plan, props.rateCard, diskFor(plan))
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
		<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
			<button
				v-for="plan in presets"
				:key="plan.plan"
				type="button"
				:aria-pressed="selectedPlan === plan.plan"
				:disabled="diskTooSmall(plan) || priceFor(plan) === null || priceFor(plan)! > available"
				class="flex flex-col rounded-6 border border-outline-gray-2 p-4 text-start transition-colors hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-outline-gray-4 disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:border-outline-gray-6"
				@click="selectedPlan = plan.plan"
			>
				<span class="flex w-full items-center justify-between gap-2">
					<span class="text-sm-medium text-ink-gray-7"
						>{{ planSize(plan) }}</span
					>
					<Badge
						v-if="currentPlan === plan.plan"
						label="Current"
						theme="gray"
						variant="subtle"
						size="sm"
					/>
				</span>
				<span class="mt-2 block text-2xl-semibold text-ink-gray-9">
					{{ priceFor(plan) === null ? 'Price unavailable' : money(priceFor(plan)!, plan.currency, { trimTrailingZeros: true }) }}
					<span v-if="priceFor(plan) !== null" class="text-sm text-ink-gray-5"
						>{{ plan.billing_cycle === 'Annual' ? '/yr' : '/mo' }}</span
					>
				</span>
				<span class="mt-2 block text-p-sm text-ink-gray-5">
					{{ planAllowances(plan, { diskGigabytes: diskFor(plan) }) }}
				</span>
				<span
					v-if="diskTooSmall(plan)"
					class="mt-1 block text-p-xs text-ink-gray-5"
				>
					Needs at least {{ minDisk }} GB storage
				</span>
				<span
					v-else-if="priceFor(plan)! > available"
					class="mt-1 text-p-sm text-ink-gray-5"
				>
					Over your spending limit
				</span>
				<span
					v-else-if="omitDisk && currentDisk != null && currentDisk > planQuantity(plan, 'Disk')"
					class="mt-1 text-p-sm text-ink-gray-5"
				>
					Includes your retained storage
				</span>
			</button>

			<button
				v-if="profile"
				type="button"
				:aria-pressed="isCustom"
				class="flex items-center gap-4 rounded-6 border border-outline-gray-2 p-4 text-start transition-colors hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-outline-gray-4 aria-pressed:border-outline-gray-6 sm:col-span-2"
				@click="pickCustom"
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
					<span class="block truncate text-sm text-ink-gray-5"
						>{{ isCustom && customSpec
							? customSpec
							: 'Pick exactly the vCPU, memory and disk you need' }}</span
					>
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
				:minimum-disk="currentDisk"
				:fixed-disk="omitDisk ? currentDisk : undefined"
			/>
			<p v-if="matchingPreset" class="mt-3 text-p-xs text-ink-gray-5">
				The
				<span class="text-p-xs-medium text-ink-gray-7"
					>{{ matchingPreset.title }}</span
				>
				preset offers this exact shape. It may be cheaper than building it à la
				carte.
			</p>
		</div>

		<p v-if="includedTransferGigabytes" class="text-p-sm text-ink-gray-5">
			Every server includes
			{{ formatTransfer(includedTransferGigabytes) }}
			of transfer a month.
		</p>
	</div>
</template>
