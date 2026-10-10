import { useCall } from 'frappe-ui'
import { computed, type Ref, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { usePlans } from '@/composables/usePlans'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import {
	configIncludes,
	estimateConfig,
	rateCardComplete,
} from '@/lib/composed'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { money } from '@/lib/format'
import { planQuantity } from '@/lib/plans'
import type { ComposedConfig, Plan, Profile } from '@/types/api'

interface ResizeCallbacks {
	close: () => void
	resized: () => void
}

export function useResizeServer(
	server: Readonly<Ref<VirtualMachineRow | null>>,
	isOpen: Readonly<Ref<boolean>>,
	callbacks: ResizeCallbacks,
) {
	const { activeTeam } = useSession()
	const activeTeamId = computed(() => activeTeam.value ?? '')

	const region = computed(() => server.value?.region ?? null)
	const serverIsLive = computed(
		() =>
			server.value?.status === 'Running' || server.value?.status === 'Paused',
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
			server: server.value?.resource_id ?? '',
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

	// A preset name, or `custom:<profile>` for a designed config in that profile — the
	// exact shape PlanGroup speaks (matching the New Server flow).
	const selectedPlan = ref<string | null>(null)
	const composedConfig = ref<ComposedConfig | null>(null)
	// The default keeps the disk, so the server can still move to a smaller size later.
	const computeOnly = ref(true)
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
	const configuredPlan = computed(() =>
		plans.value.find((plan) => plan.plan === configCall.data?.plan),
	)

	// The current shape, so the custom designer opens pre-filled on the running config.
	const initial = computed<ComposedConfig | null>(() =>
		resizable.value
			? {
					sub_category:
						configCall.data!.sub_category ??
						configuredPlan.value?.sub_category ??
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

	// Start clean on every open. Keyed on the server id, so a refetch of the same
	// server while the dialog is open keeps the selection.
	watch(
		[isOpen, () => server.value?.resource_id],
		([opened, serverId]) => {
			if (!opened || !serverId) return

			selectedPlan.value = null
			composedConfig.value = null
			activeTab.value = ''
			computeOnly.value = true

			if (activeTeamId.value) configCall.reload()
		},
		{ immediate: true },
	)

	const currentPlanKey = computed(() => {
		const cfg = configCall.data
		if (!cfg?.resizable) return null
		if (cfg.composed) return `custom:${cfg.sub_category || soleClass.value}`
		return cfg.plan ?? null
	})
	const currentDisk = computed(() => configCall.data?.disk_gb ?? 0)
	const selectedPreset = computed(() =>
		isCustomSel.value
			? undefined
			: plans.value.find((p) => p.plan === selectedPlan.value),
	)

	const targetCompute = computed<ComposedConfig | null>(() => {
		if (isCustomSel.value) return composedConfig.value

		const plan = selectedPreset.value
		if (!plan) return null

		return {
			sub_category: plan.sub_category,
			vcpus: planQuantity(plan, 'Compute'),
			memory_gb: planQuantity(plan, 'Memory'),
			disk_gb: initial.value?.disk_gb ?? planQuantity(plan, 'Disk'),
		}
	})

	// Without "CPU and memory only" the disk follows the chosen size. It never shrinks.
	const targetDisk = computed(() => {
		if (computeOnly.value) return currentDisk.value

		const chosen = isCustomSel.value
			? (composedConfig.value?.disk_gb ?? 0)
			: selectedPreset.value
				? planQuantity(selectedPreset.value, 'Disk')
				: 0
		return Math.max(currentDisk.value, chosen)
	})

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
	const diskChanged = computed(() => targetDisk.value > currentDisk.value)
	const changed = computed(() => computeChanged.value || diskChanged.value)
	const needsRestart = computed(
		() => serverIsLive.value && computeChanged.value,
	)

	const downtimeNote = computed(() =>
		diskChanged.value && !needsRestart.value
			? 'The disk grows while the server runs. No data is lost.'
			: 'The server stops while it resizes. It takes a few minutes, and no data is lost.',
	)

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

	// A preset keeps its bundle price and pays the disk rate only for GB grown beyond what the
	// plan already includes, so growing disk always adds to the price. A custom config is priced
	// à la carte from the rate card.
	function getMonthlyPrice(
		shape: ComposedConfig,
		plan: Plan | undefined,
	): number | null {
		if (plan) {
			const extraDisk = Math.max(0, shape.disk_gb - planQuantity(plan, 'Disk'))
			return plan.rate + extraDisk * (rateCard.value.Disk?.rate ?? 0)
		}

		if (rateCardComplete(rateCard.value))
			return estimateConfig(shape, rateCard.value)

		return null
	}

	const formatMonthly = (amount: number | null, unit?: string): string => {
		if (amount == null) return ''

		const currencyCode = unit || currency.value || lock.value?.currency || 'USD'
		return `${money(amount, currencyCode, { trimTrailingZeros: true })}/mo`
	}

	const currentPrice = computed(() => {
		if (lock.value)
			return formatMonthly(lock.value.locked_rate, lock.value.currency)

		const shape = initial.value
		if (!shape) return ''

		const plan = configCall.data?.composed ? undefined : configuredPlan.value
		return formatMonthly(getMonthlyPrice(shape, plan), plan?.currency)
	})

	const totalPrice = computed(() => {
		const shape = totalShape.value
		if (!shape || !changed.value) return ''

		const plan = selectedPreset.value
		return formatMonthly(getMonthlyPrice(shape, plan), plan?.currency)
	})

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
	watch([selectedPlan, composedConfig, computeOnly], () => resizeCall.reset())

	async function confirm() {
		const currentServer = server.value
		const compute = targetCompute.value
		if (
			!currentServer?.resource_id ||
			!activeTeamId.value ||
			!changed.value ||
			!compute
		)
			return

		// central.api.servers.resize_server resolves the subscription, re-locks
		// billing, and asks Atlas to apply the shape.
		const disk = targetDisk.value
		const plan = selectedPreset.value
		const target = {
			team: activeTeamId.value,
			resource_id: currentServer.resource_id,
		}
		const payload = plan
			? { ...target, plan: plan.plan, disk_gigabytes: disk }
			: {
					...target,
					includes: configIncludes({ ...compute, disk_gb: disk }),
					sub_category: compute.sub_category,
					disk_gigabytes: disk,
				}

		await resizeCall.submit(payload)
		if (resizeCall.error) return

		// The reshape runs in the background, so confirm and close instead of holding the dialog.
		const name = currentServer.title || currentServer.resource_id
		successToast(
			resizeCall.data?.queued
				? `Resizing ${name}. The server list shows its progress.`
				: `Resized ${name}.`,
		)
		callbacks.resized()
		callbacks.close()
	}

	return {
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
		computeOnly,
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
		currentPrice,
		totalPrice,
		downtimeNote,
		changed,
		confirm,
	}
}
