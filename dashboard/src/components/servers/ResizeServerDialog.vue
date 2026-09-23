<script setup lang="ts">
import {
	Alert,
	Button,
	Checkbox,
	Dialog,
	LoadingIndicator,
	Tabs,
	useCall,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import { usePlans } from '@/composables/usePlans'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import {
	configIncludes,
	estimateConfig,
	formatGb,
	formatVcpu,
	rateCardComplete,
} from '@/lib/composed'
import { money } from '@/lib/format'
import { planResources } from '@/lib/plans'
import { getErrorMessage, successToast } from '@/lib/toast'
import type { ComposedConfig, Plan, Profile } from '@/types/api'

// Resize sends the new size. Atlas moves the server if this host cannot fit it.
// Disk stays put unless they check "Grow the disk". A larger disk cannot shrink.
// A CPU or memory change on a running server restarts it. Controlled by the page
// via v-model:server.
const props = defineProps<{ server: VirtualMachineRow | null }>()
const emit = defineEmits<{
	'update:server': [server: VirtualMachineRow | null]
	resized: []
}>()

const { activeTeam } = useSession()
const activeTeamId = computed(() => activeTeam.value ?? '')

const region = computed(() => props.server?.cluster ?? null)
const serverIsLive = computed(
	() => props.server?.status === 'Running' || props.server?.status === 'Paused',
)

// The config running on this server (current shape + preset, and the subscription
// the resize re-locks). Drives both the pre-selection and the headroom exclusion.
type ComposedConfigResponse = {
	resizable: boolean
	composed?: boolean
	subscription?: string
	sub_category?: string | null
	plan?: string | null
	vcpus?: number
	memory_gb?: number
	disk_gb?: number
	lock?: {
		locked_rate: number
		list_rate: number
		currency: string
		/** How much per month sits between this server's rate and today's list. */
		gives_up: number
	} | null
}
const configCall = useCall<
	ComposedConfigResponse,
	{ server: string; team: string }
>({
	url: method(API.composedConfig),
	params: () => ({
		server: props.server?.resource_id ?? '',
		team: activeTeamId.value,
	}),
	immediate: false,
})
const subscription = computed(() => configCall.data?.subscription ?? null)

// This server is held below today's price, and a resize re-prices at current
// rates (ADR 0010). Say so before they commit: the rate does not come back, not
// even by resizing to the size they are on now.
const lock = computed(() => configCall.data?.lock ?? null)
const losesLockedRate = computed(() => (lock.value?.gives_up ?? 0) > 0)

// The region's menu, with this server's own spend freed back into the headroom so it
// can grow into its own budget (exclude_subscription).
const {
	groups,
	classes,
	plans,
	rateCard,
	profiles,
	available,
	currency,
	capacity,
	loading: plansLoading,
} = usePlans(region, subscription)

const open = computed({
	get: () => !!props.server,
	set: (v: boolean) => {
		// Don't let a stray close (Esc / backdrop) abandon an in-flight resize.
		if (!v && !resizeCall.loading) emit('update:server', null)
	},
})

// A preset name, or `custom:<profile>` for a designed config in that profile — the
// exact shape PlanGroup speaks (matching the New Server flow).
const selectedPlan = ref<string | null>(null)
const composedConfig = ref<ComposedConfig | null>(null)
// Disk stays put unless they opt in. Growing it cannot be undone.
const growDisk = ref(false)
const selectedDisk = ref<number | null>(null)
const isCustomSel = computed(() =>
	(selectedPlan.value ?? '').startsWith('custom:'),
)
const resizable = computed(() => configCall.data?.resizable === true)

const canDesign = computed(
	() => rateCardComplete(rateCard.value) && profiles.value.length > 0,
)
function profileFor(cls: string): Profile | null {
	return profiles.value.find((p) => p.sub_category === cls) ?? null
}
function designableProfile(cls: string): Profile | null {
	return canDesign.value ? profileFor(cls) : null
}
const hasTabs = computed(() => classes.value.length > 1)
const classTabs = computed(() =>
	classes.value.map((label) => ({ label, value: label })),
)
const activeTab = ref('')
const soleClass = computed(() => classes.value[0] ?? 'General')
const flatPresets = computed(() => groups.value[soleClass.value] ?? [])
const flatProfile = computed<Profile | null>(() =>
	canDesign.value
		? (profileFor(soleClass.value) ?? profiles.value[0] ?? null)
		: null,
)
const nothingToShow = computed(
	() => !hasTabs.value && !flatPresets.value.length && !flatProfile.value,
)

// The current shape, so the custom designer opens pre-filled on the running config.
const initial = computed<ComposedConfig | null>(() =>
	resizable.value
		? {
				sub_category:
					configCall.data!.sub_category ??
					profiles.value[0]?.sub_category ??
					'',
				vcpus: configCall.data!.vcpus ?? 0,
				memory_gb: configCall.data!.memory_gb ?? 0,
				disk_gb: configCall.data!.disk_gb ?? 0,
			}
		: null,
)
// The custom designer seeds its profile from initial.sub_category, so only hand
// `initial` to the group whose profile actually matches — other tabs start fresh.
function initialFor(profile: Profile | null): ComposedConfig | null {
	return profile && initial.value?.sub_category === profile.sub_category
		? initial.value
		: null
}

// Pre-select what the server runs today, once the config + menu have loaded: the
// current preset row, or the custom row in its profile pre-filled with its shape.
watch([() => configCall.data, plans], () => {
	if (!resizable.value || selectedPlan.value || !classes.value.length) return
	const cfg = configCall.data!
	if (cfg.composed) {
		const cls = cfg.sub_category ?? soleClass.value
		selectedPlan.value = `custom:${cls}`
		composedConfig.value = initial.value
		activeTab.value = cls
	} else if (cfg.plan && plans.value.some((p) => p.plan === cfg.plan)) {
		selectedPlan.value = cfg.plan
		const cls =
			plans.value.find((p) => p.plan === cfg.plan)?.sub_category ??
			soleClass.value
		activeTab.value = cls
	}
})

// Reset when the dialog opens on a different server.
watch(
	() => props.server,
	(server) => {
		selectedPlan.value = null
		composedConfig.value = null
		activeTab.value = ''
		growDisk.value = false
		selectedDisk.value = null
		if (server && activeTeamId.value) configCall.reload()
	},
)

const currentPlanKey = computed(() => {
	const cfg = configCall.data
	if (!cfg?.resizable) return null
	if (cfg.composed) return `custom:${cfg.sub_category || soleClass.value}`
	return cfg.plan ?? null
})
const currentDisk = computed(() => configCall.data?.disk_gb ?? 0)

const largerDisks = computed(() => {
	const fromProfiles = profiles.value.flatMap((profile) => profile.disk_steps)
	const fromPlans = plans.value.map(
		(plan) =>
			plan.includes.find((inc) => inc.resource_type === 'Disk')?.quantity ?? 0,
	)
	return [...new Set([...fromProfiles, ...fromPlans])]
		.filter((gb) => gb > currentDisk.value)
		.sort((a, b) => a - b)
})
watch(largerDisks, (steps) => {
	if (!steps.length) {
		selectedDisk.value = null
		growDisk.value = false
		return
	}
	if (selectedDisk.value == null || !steps.includes(selectedDisk.value))
		selectedDisk.value = steps[0]
})

const targetCompute = computed<ComposedConfig | null>(() => {
	const current = initial.value
	if (isCustomSel.value) return composedConfig.value
	const plan = plans.value.find((p) => p.plan === selectedPlan.value)
	if (!plan) return null
	const qty = (type: string) =>
		plan.includes.find((inc) => inc.resource_type === type)?.quantity ?? 0
	return {
		sub_category: plan.sub_category,
		vcpus: qty('Compute'),
		memory_gb: qty('Memory'),
		disk_gb: current?.disk_gb ?? qty('Disk'),
	}
})
const targetDisk = computed(() =>
	growDisk.value && selectedDisk.value != null
		? selectedDisk.value
		: currentDisk.value,
)
const computeChanged = computed(() => {
	const next = targetCompute.value
	const now = initial.value
	if (!selectedPlan.value || !next || !now) return false
	if (isCustomSel.value && !configCall.data?.composed) return true
	if (!isCustomSel.value && selectedPlan.value !== configCall.data?.plan)
		return true
	return (
		next.vcpus !== now.vcpus ||
		next.memory_gb !== now.memory_gb ||
		next.sub_category !== now.sub_category
	)
})
const diskChanged = computed(
	() => growDisk.value && targetDisk.value > currentDisk.value,
)

const changed = computed(() => computeChanged.value || diskChanged.value)
const needsRestart = computed(() => serverIsLive.value && computeChanged.value)
const resizeLabel = computed(() => {
	if (needsRestart.value) return 'Restart and resize'
	if (diskChanged.value && !computeChanged.value) return 'Grow disk'
	return 'Resize'
})
const totalShape = computed(() => {
	const compute = targetCompute.value ?? initial.value
	if (!compute) return null
	return {
		vcpus: compute.vcpus,
		memory_gb: compute.memory_gb,
		disk_gb: targetDisk.value || compute.disk_gb,
		sub_category: compute.sub_category,
	}
})
const diskRate = computed(() => rateCard.value.Disk?.rate ?? 0)

// A preset keeps its bundle price and pays the disk rate only for GB grown beyond what the
// plan already includes, so growing disk always adds to the price. A custom config is priced
// à la carte from the rate card.
function presetPrice(plan: Plan, diskGb: number): number {
	const extra = Math.max(0, diskGb - planResources(plan).disk_gigabytes)
	return plan.rate + extra * diskRate.value
}
const totalPrice = computed(() => {
	const shape = totalShape.value
	if (!shape) return ''
	const plan = plans.value.find((p) => p.plan === selectedPlan.value)
	const cur = currency.value || lock.value?.currency || 'USD'
	let amount: number | null = null
	let unit = cur
	if (plan && !isCustomSel.value) {
		amount = presetPrice(plan, shape.disk_gb)
		unit = plan.currency
	} else if (rateCardComplete(rateCard.value)) {
		amount = estimateConfig(shape, rateCard.value)
	} else if (!changed.value && lock.value) {
		amount = lock.value.locked_rate
		unit = lock.value.currency
	}
	return amount == null
		? ''
		: `${money(amount, unit, { trimTrailingZeros: true })} / mo`
})
function priceForDisk(diskGb: number): string {
	const shape = totalShape.value
	if (!shape) return ''
	const plan = plans.value.find((p) => p.plan === selectedPlan.value)
	const cur = currency.value || lock.value?.currency || 'USD'
	if (plan && !isCustomSel.value)
		return `${money(presetPrice(plan, diskGb), plan.currency, { trimTrailingZeros: true })} / mo`
	if (!rateCardComplete(rateCard.value)) return ''
	const amount = estimateConfig({ ...shape, disk_gb: diskGb }, rateCard.value)
	return `${money(amount, cur, { trimTrailingZeros: true })} / mo`
}

const resizeCall = useCall<
	{ subscription: string; queued: boolean; resized: boolean },
	Record<string, unknown>
>({
	url: method(API.resizeServer),
	method: 'POST',
	immediate: false,
})

// A failed resize keeps the dialog open with the reason. Cleared when the
// selection changes so a fresh attempt starts clean.
const resizeError = computed(() =>
	resizeCall.error
		? getErrorMessage(resizeCall.error, "Couldn't resize the server.")
		: '',
)
watch([selectedPlan, composedConfig, growDisk, selectedDisk], () =>
	resizeCall.reset(),
)

async function confirm() {
	const server = props.server
	const compute = targetCompute.value
	if (!server?.resource_id || !activeTeamId.value || !changed.value || !compute)
		return
	const disk = targetDisk.value
	const plan = plans.value.find((p) => p.plan === selectedPlan.value)
	// central.api.servers.resize_server resolves the subscription, re-locks
	// billing, and asks Atlas to apply the shape.
	const payload =
		plan && !isCustomSel.value
			? {
					team: activeTeamId.value,
					resource_id: server.resource_id,
					plan: plan.plan,
					disk_gigabytes: disk,
				}
			: {
					team: activeTeamId.value,
					resource_id: server.resource_id,
					includes: configIncludes({ ...compute, disk_gb: disk }),
					sub_category: compute.sub_category,
					disk_gigabytes: disk,
				}
	await resizeCall.submit(payload)
	if (!resizeCall.error) {
		// The reshape runs in the background now — the server shows "Resizing" in the list
		// and comes back on its own — so confirm and close instead of holding the dialog.
		const name = props.server?.title || props.server?.resource_id
		successToast(
			resizeCall.data?.queued
				? `Resizing ${name}. The server list shows its progress.`
				: `Resized ${name}.`,
		)
		emit('resized')
		open.value = false
	}
}
</script>

<template>
	<Dialog v-model="open" title="Resize server" size="3xl">
		<template #default>
			<!-- Resize runs on the host and can take a while for a data-heavy server, so
           show a clear in-progress state and hold the dialog open until it lands. -->
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
