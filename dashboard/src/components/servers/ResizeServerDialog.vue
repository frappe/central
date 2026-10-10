<script setup lang="ts">
import {
	Alert,
	Button,
	Checkbox,
	Dialog,
	LoadingIndicator,
	Tabs,
} from 'frappe-ui'
import { computed, toRef } from 'vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import { useResizeServer } from '@/composables/useResizeServer'
import type { VirtualMachineRow } from '@/composables/useServers'
import { formatGb } from '@/lib/composed'
import { money } from '@/lib/format'

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
	downtimeNote,
	changed,
	confirm,
} = useResizeServer(toRef(props, 'server'), model, {
	close: () => (model.value = false),
	resized: () => emit('resized'),
})

const open = computed({
	get: () => model.value,
	set: (value: boolean) => {
		if (!value && !resizeCall.loading) model.value = false
	},
})
</script>

<template>
	<Dialog v-model="open" title="Resize server" size="3xl">
		<template #default>
			<!-- Keep the dialog stable while Central accepts the resize request. -->
			<div
				v-if="resizeCall.loading"
				class="flex flex-col items-center gap-3 py-10 text-center"
			>
				<LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
				<p class="text-p-base font-medium text-ink-gray-8">Starting resize…</p>
				<p class="max-w-xs text-p-sm text-ink-gray-5">
					The reshape runs in the background. The server shows “Resizing” in the
					list and comes back on its own when it’s done.
				</p>
			</div>
			<p
				v-else-if="configCall.loading || plansLoading"
				class="text-p-sm text-ink-gray-5"
			>
				Loading…
			</p>
			<p
				v-else-if="!resizable || nothingToShow"
				class="text-p-sm text-ink-gray-5"
			>
				This server can't be resized right now.
			</p>
			<div v-else class="space-y-4">
				<Alert v-if="resizeError" theme="red" :title="resizeError" />
				<Alert
					v-if="losesLockedRate && lock"
					theme="amber"
					title="Resizing will change your rate"
					:description="`You pay ${money(lock.locked_rate, lock.currency)}/mo for this size; it now lists at ${money(lock.list_rate, lock.currency)}/mo. Any resize is priced at today's rates, and the old rate doesn't come back, including if you resize to this size again later.`"
				/>

				<div class="space-y-2 text-p-base text-ink-gray-7">
					<p>
						You can change CPU and memory only, or grow the disk too. You can
						only move to a smaller size later if you keep the disk as it is.
					</p>
					<p>{{ downtimeNote }}</p>
				</div>

				<div class="rounded-6 border border-outline-gray-2 px-3 py-2.5">
					<Checkbox
						v-model="computeOnly"
						label="CPU and memory only"
						:description="`Keeps the ${formatGb(currentDisk)} GB disk as it is.`"
					/>
				</div>

				<Tabs v-if="hasTabs" v-model="activeTab" :tabs="classTabs">
					<template #tab-panel="{ tab }">
						<PlanGroup
							class="pt-4"
							:omit-disk="computeOnly"
							:min-disk="computeOnly ? undefined : currentDisk"
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
			</div>
		</template>
		<template #actions>
			<div
				v-if="resizable && !resizeCall.loading"
				class="flex items-center justify-end gap-4"
			>
				<p v-if="totalPrice" class="text-p-sm text-ink-gray-6">
					{{ currentPrice }}
					<span
						class="lucide-arrow-right mx-1 inline-block size-3.5 align-[-2px]"
						aria-label="to"
					/>
					<span class="font-medium text-ink-gray-9">{{ totalPrice }}</span>
				</p>
				<Button
					variant="solid"
					label="Resize"
					:disabled="!changed"
					@click="confirm"
				/>
			</div>
		</template>
	</Dialog>
</template>
