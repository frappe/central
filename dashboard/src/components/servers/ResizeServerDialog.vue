<script setup lang="ts">
import {
	Alert,
	Button,
	Dialog,
	LoadingIndicator,
	Radio,
	RadioGroup,
	Skeleton,
	Tabs,
} from 'frappe-ui'
import { computed, ref, toRef } from 'vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import TrialUpgradePanel from '@/components/servers/TrialUpgradePanel.vue'
import { useResizeServer } from '@/composables/useResizeServer'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useTrialConversion } from '@/composables/useTrialConversion'
import { configSpecs } from '@/lib/composed'
import { formatGb } from '@/lib/units'

interface Props {
	server: VirtualMachineRow | null
}

const props = defineProps<Props>()
const model = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ resized: [] }>()

const {
	configCall,
	resizeCall,
	plansLoading,
	resizable,
	trial,
	trialPlans,
	starting,
	nothingToShow,
	resizeError,
	losesLockedRate,
	lock,
	hasTabs,
	activeTab,
	classTabs,
	currentDisk,
	currentPlanKey,
	groups,
	designableProfile,
	rateCard,
	available,
	currency,
	capacity,
	initialFor,
	selectedPlan,
	composedConfig,
	flatPresets,
	flatProfile,
	computeOnly,
	currentPrice,
	totalPrice,
	totalShape,
	selectionError,
	canConfirm,
	optionsError,
	reloadOptions,
	downtimeNote,
	changed,
	confirm,
} = useResizeServer(toRef(props, 'server'), model, {
	close: () => (model.value = false),
	resized: () => emit('resized'),
})

const { convertedPlan, awaitConversion } = useTrialConversion(
	trial,
	() => configCall.reload(),
	model,
)

const trialPanel = ref<InstanceType<typeof TrialUpgradePanel> | null>(null)

const open = computed({
	get: () => model.value,
	set: (value: boolean) => {
		if (!value && !resizeCall.loading) model.value = false
	},
})
</script>

<template>
	<Dialog
		v-model="open"
		:title="trial ? 'Upgrade from free trial' : 'Resize server'"
		size="3xl"
	>
		<template #default>
			<!-- Keep the dialog stable while Central accepts the resize request. -->
			<div
				v-if="resizeCall.loading"
				class="flex flex-col items-center gap-3 py-10 text-center"
			>
				<LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
				<p class="text-p-base-medium text-ink-gray-8">Starting resize…</p>
				<p class="max-w-xs text-p-sm text-ink-gray-5">
					Follow progress in the server list.
				</p>
			</div>
			<div
				v-else-if="(configCall.loading && !trial && !starting) || plansLoading"
				class="space-y-4"
				aria-busy="true"
				aria-label="Loading resize options"
			>
				<div class="space-y-2">
					<Skeleton class="h-4 w-full rounded-4" />
					<Skeleton class="h-4 w-2/3 rounded-4" />
				</div>
				<div class="grid gap-3 sm:grid-cols-2">
					<Skeleton v-for="index in 2" :key="index" class="h-16 rounded-6" />
				</div>
				<div class="grid gap-3 sm:grid-cols-3">
					<Skeleton v-for="index in 6" :key="index" class="h-24 rounded-6" />
				</div>
			</div>
			<div v-else-if="optionsError" class="space-y-3">
				<Alert
					theme="red"
					title="Couldn't load resize options"
					:description="optionsError"
				/>
				<Button label="Retry" @click="reloadOptions" />
			</div>
			<TrialUpgradePanel
				v-else-if="trial"
				ref="trialPanel"
				:trial="trial"
				:plans="trialPlans"
				:checking="configCall.loading"
				:server-id="server?.resource_id ?? ''"
				@check="awaitConversion"
			/>
			<Alert
				v-else-if="starting"
				theme="blue"
				title="Your payment method is confirmed"
				description="We are moving your server to its paid plan. This takes a few minutes, then the plans show here."
			/>
			<p
				v-else-if="!resizable || nothingToShow"
				class="text-p-sm text-ink-gray-5"
			>
				This server can't be resized right now.
			</p>
			<div v-else class="space-y-4">
				<Alert
					v-if="convertedPlan"
					theme="green"
					:title="`You're on the ${convertedPlan.title} plan`"
					description="Billing has started. Choose a bigger size below, or close this dialog to stay on this plan."
				/>
				<Alert v-if="resizeError" theme="red" :title="resizeError" />
				<Alert
					v-if="losesLockedRate && lock"
					theme="amber"
					title="Resizing will change your rate"
					description="Resizing uses today’s rates. Your current rate cannot be restored."
				/>

				<p class="text-p-sm text-ink-gray-7">
					Choose a new CPU and memory size. You can also increase storage, but
					you cannot reduce it later.
				</p>
				<RadioGroup v-model="computeOnly" label="Storage" padded>
					<Radio
						:value="true"
						:label="`Keep current ${formatGb(currentDisk)} GB disk size`"
					/>
					<Radio :value="false" label="Increase storage">
						<template #description>
							<strong class="text-p-sm-medium text-ink-amber-7">
								Disk size cannot be decreased later.
							</strong>
						</template>
					</Radio>
				</RadioGroup>
				<p class="text-p-sm text-ink-gray-6">Prices include storage.</p>

				<Tabs v-if="hasTabs" v-model="activeTab" :tabs="classTabs">
					<template #tab-panel="{ tab }">
						<PlanGroup
							class="pt-4"
							:omit-disk="computeOnly"
							:min-disk="computeOnly ? undefined : currentDisk"
							:current-disk="currentDisk"
							:current-plan="currentPlanKey"
							:presets="groups[tab.value] ?? []"
							:profile="designableProfile(String(tab.value))"
							:rate-card="rateCard"
							:available="available ?? 0"
							:currency="currency ?? 'USD'"
							:capacity="capacity"
							:initial="initialFor(designableProfile(String(tab.value)))"
							v-model:selected-plan="selectedPlan"
							v-model:composed-config="composedConfig"
						/>
					</template>
				</Tabs>
				<PlanGroup
					v-else
					:omit-disk="computeOnly"
					:min-disk="computeOnly ? undefined : currentDisk"
					:current-disk="currentDisk"
					:current-plan="currentPlanKey"
					:presets="flatPresets"
					:profile="flatProfile"
					:rate-card="rateCard"
					:available="available ?? 0"
					:currency="currency ?? 'USD'"
					:capacity="capacity"
					:initial="initialFor(flatProfile)"
					v-model:selected-plan="selectedPlan"
					v-model:composed-config="composedConfig"
				/>
				<Alert v-if="selectionError" theme="red" :title="selectionError" />
				<div
					v-if="totalShape && changed"
					class="space-y-2 border-t border-outline-gray-2 pt-4"
					aria-live="polite"
				>
					<p class="text-sm-medium text-ink-gray-9">After resizing</p>
					<p class="text-p-sm text-ink-gray-7">{{ configSpecs(totalShape) }}</p>
					<p class="text-p-sm text-ink-gray-6">
						{{ downtimeNote }}
						Your files are kept.
					</p>
				</div>
			</div>
		</template>
		<template #actions>
			<div v-if="starting" class="flex justify-end">
				<Button
					label="Check again"
					:loading="configCall.loading"
					@click="configCall.reload()"
				/>
			</div>
			<div v-else-if="trial && trialPanel" class="flex justify-end">
				<Button
					v-if="trial.can_keep"
					variant="solid"
					icon-left="lucide-play"
					label="Keep this site"
					:disabled="!trialPanel?.canContinue"
					:loading="trialPanel?.saving"
					@click="trialPanel?.keep()"
				/>
				<Button
					v-else-if="trial.held"
					variant="solid"
					label="Use this plan"
					:disabled="!trialPanel?.canContinue"
					:loading="trialPanel?.saving || configCall.loading"
					@click="trialPanel?.choosePlan()"
				/>
				<Button
					v-else-if="trialPanel?.methodAdded"
					label="Check again"
					:loading="configCall.loading"
					@click="configCall.reload()"
				/>
				<Button
					v-else
					variant="solid"
					icon-left="lucide-credit-card"
					label="Add payment method"
					:disabled="!trialPanel?.canContinue"
					:loading="trialPanel?.saving"
					@click="trialPanel?.addMethod()"
				/>
			</div>
			<div
				v-else-if="resizable && !resizeCall.loading"
				class="flex items-center justify-end gap-4"
			>
				<p v-if="totalPrice" class="text-p-sm text-ink-gray-6">
					{{ currentPrice }}
					<span
						class="lucide-arrow-right mx-1 inline-block size-3.5 align-[-2px]"
						aria-label="to"
					/>
					<span class="text-p-sm-medium text-ink-gray-9">{{ totalPrice }}</span>
				</p>
				<Button
					variant="solid"
					label="Resize"
					:disabled="!canConfirm"
					@click="confirm"
				/>
			</div>
		</template>
	</Dialog>
</template>
