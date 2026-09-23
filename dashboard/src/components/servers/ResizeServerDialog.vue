<script setup lang="ts">
import {
	Alert,
	Button,
	Checkbox,
	Dialog,
	LoadingIndicator,
	Tabs,
} from 'frappe-ui'
import { toRef } from 'vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import { useResizeServer } from '@/composables/useResizeServer'
import type { VirtualMachineRow } from '@/composables/useServers'
import { formatGb, formatVcpu } from '@/lib/composed'
import { money } from '@/lib/format'

interface Props {
	server: VirtualMachineRow | null
}

const props = defineProps<Props>()
const emit = defineEmits<{
	'update:server': [server: VirtualMachineRow | null]
	resized: []
}>()

const {
	open,
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
	growDisk,
	largerDisks,
	selectedDisk,
	priceForDisk,
	totalShape,
	totalPrice,
	resizeLabel,
	changed,
	confirm,
} = useResizeServer(toRef(props, 'server'), {
	close: () => emit('update:server', null),
	resized: () => emit('resized'),
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
			<div v-else class="space-y-5">
				<Alert v-if="resizeError" theme="red" :title="resizeError" />
				<Alert
					v-if="losesLockedRate && lock"
					theme="amber"
					title="Resizing will change your rate"
					:description="`You pay ${money(lock.locked_rate, lock.currency)}/mo for this size; it now lists at ${money(lock.list_rate, lock.currency)}/mo. Any resize is priced at today's rates, and the old rate doesn't come back, including if you resize to this size again later.`"
				/>
				<div class="space-y-3">
					<p class="text-p-sm text-ink-gray-6">
						Changing CPU or memory restarts the server.
					</p>

					<Tabs v-if="hasTabs" v-model="activeTab" :tabs="classTabs">
						<template #tab-panel="{ tab }">
							<PlanGroup
								class="pt-4"
								omit-disk
								:min-disk="currentDisk"
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
						omit-disk
						:min-disk="currentDisk"
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

				<div class="space-y-3 border-t border-outline-gray-2 pt-4">
					<Checkbox
						v-model="growDisk"
						label="Grow the disk"
						:description="
							largerDisks.length
								? 'Storage can only be increased. If you increase it, you cannot resize to a smaller plan later.'
								: 'No larger disk is available.'
						"
						:disabled="!largerDisks.length"
					/>
					<div v-if="growDisk" class="space-y-1.5">
						<label
							v-for="gb in largerDisks"
							:key="gb"
							:class="[
								'flex cursor-pointer items-center gap-3 rounded-6 border px-3 py-2.5 text-p-sm',
								selectedDisk === gb
									? 'border-outline-gray-4 bg-surface-gray-1'
									: 'border-outline-gray-2 hover:border-outline-gray-3',
							]"
						>
							<input
								v-model="selectedDisk"
								type="radio"
								class="peer sr-only"
								:value="gb"
							/>
							<span
								aria-hidden="true"
								class="size-3.5 shrink-0 rounded-full border border-outline-gray-4 peer-checked:border-4 peer-checked:border-outline-gray-5"
							/>
							<span class="font-medium text-ink-gray-9"
								>{{ formatGb(gb) }}
								GB</span
							>
							<span
								v-if="priceForDisk(gb)"
								class="ml-auto text-p-sm font-medium text-ink-gray-9"
								>{{ priceForDisk(gb) }}</span
							>
						</label>
					</div>
				</div>

				<div
					v-if="totalShape"
					class="flex items-center justify-between gap-6 rounded-6 border border-outline-gray-2 bg-surface-gray-1 px-4 py-3"
				>
					<div class="min-w-0">
						<p class="text-p-sm font-medium text-ink-gray-9">Monthly total</p>
						<p class="text-p-sm text-ink-gray-6">
							{{ formatVcpu(totalShape.vcpus) }}
							vCPU ·
							{{ formatGb(totalShape.memory_gb) }}
							GB RAM ·
							{{ formatGb(totalShape.disk_gb) }}
							GB disk
						</p>
					</div>
					<p
						v-if="totalPrice"
						class="shrink-0 text-p-base font-medium text-ink-gray-9"
					>
						{{ totalPrice }}
					</p>
				</div>
			</div>
		</template>
		<template #actions>
			<div
				v-if="resizable && !resizeCall.loading"
				class="flex items-center justify-end"
			>
				<Button
					variant="solid"
					:label="resizeLabel"
					:disabled="!changed"
					@click="confirm"
				/>
			</div>
		</template>
	</Dialog>
</template>
