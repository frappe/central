<script setup lang="ts">
import {
	Alert,
	Button,
	Dialog,
	LoadingIndicator,
	Tabs,
	useCall,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import { usePlans } from '@/composables/usePlans'
import type { AssetRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import { configIncludes, rateCardComplete } from '@/lib/composed'
import { money } from '@/lib/format'
import { getErrorMessage, successToast } from '@/lib/toast'
import type { ComposedConfig, Profile } from '@/types/api'

// Resize a server with the same plan picker used to create it (#84): its region's
// preset bundles plus a custom slider, pre-selected to whatever the server runs now.
// One action — the backend power-cycles the VM as needed (Firecracker reconfigures
// pre-boot), so there's no separate "turn off first" step. Controlled by the page
// via v-model:server.
const props = defineProps<{ server: AssetRow | null }>()
const emit = defineEmits<{
	'update:server': [server: AssetRow | null]
	resized: []
}>()

const { activeTeam } = useSession()
const activeTeamId = computed(() => activeTeam.value ?? '')

const region = computed(() => props.server?.cluster ?? null)
const needsRestart = computed(
	() => props.server?.status === 'Running' || props.server?.status === 'Paused',
)
// Be explicit that a live resize power-cycles the server (stop → resize → start),
// which the backend does automatically; a server that's already off just resizes.
const resizeLabel = computed(() =>
	needsRestart.value ? 'Restart & resize' : 'Resize',
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
	{ asset: string; team: string }
>({
	url: method(API.composedConfig),
	params: () => ({
		asset: props.server?.resource_id ?? '',
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
		if (server && activeTeamId.value) configCall.reload()
	},
)

// A confirm is meaningful only when the selection differs from what's running.
const changed = computed(() => {
	if (!selectedPlan.value) return false
	if (isCustomSel.value) {
		const c = composedConfig.value
		if (!c) return false
		if (!configCall.data?.composed) return true // preset → custom is always a change
		const i = initial.value
		return (
			!i ||
			c.vcpus !== i.vcpus ||
			c.disk_gb !== i.disk_gb ||
			c.sub_category !== i.sub_category
		)
	}
	return selectedPlan.value !== configCall.data?.plan
})

const resizeCall = useCall<
	{ subscription: string; queued: boolean; resized: boolean },
	Record<string, unknown>
>({
	url: method(API.resizeServer),
	method: 'POST',
	immediate: false,
})

// A failed resize (most often a disk downgrade — Atlas can only grow a disk) keeps
// the dialog open with the reason shown, instead of silently dropping back to the
// picker. Cleared when the selection changes so a fresh attempt starts clean.
const resizeError = computed(() =>
	resizeCall.error
		? getErrorMessage(resizeCall.error, "Couldn't resize the server.")
		: '',
)
watch([selectedPlan, composedConfig], () => resizeCall.reset())

async function confirm() {
	const sub = subscription.value
	if (!sub || !changed.value) return
	const payload =
		isCustomSel.value && composedConfig.value
			? {
					subscription: sub,
					includes: configIncludes(composedConfig.value),
					sub_category: composedConfig.value.sub_category,
				}
			: { subscription: sub, plan: selectedPlan.value }
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
	<Dialog v-model="open" title="Resize server" size="2xl">
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
					The reshape runs in the background. The server shows “Resizing” in
					the list and comes back on its own when it’s done.
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
				<div
					v-if="needsRestart"
					class="rounded-6 border border-outline-gray-2 bg-surface-gray-1 px-3 py-2.5 text-p-sm text-ink-gray-6"
				>
					Your server will be briefly stopped to apply the new size, then
					started again automatically.
				</div>

				<Tabs v-if="hasTabs" v-model="activeTab" :tabs="classTabs">
					<template #tab-panel="{ tab }">
						<PlanGroup
							class="pt-4"
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
