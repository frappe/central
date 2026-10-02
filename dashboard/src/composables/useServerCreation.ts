import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCapabilities } from '@/composables/useCapabilities'
import { useMyProfile } from '@/composables/useMyProfile'
import { usePlans } from '@/composables/usePlans'
import { useProvisioningAction } from '@/composables/useProvisioningAction'
import { useRegionalImages } from '@/composables/useRegionalImages'
import { useRegions } from '@/composables/useRegions'
import { useServerMapData } from '@/composables/useServerMapData'
import { useSession } from '@/composables/useSession'
import {
	configIncludes,
	estimateConfig,
	ramFor,
	rateCardComplete,
} from '@/lib/composed'
import { money } from '@/lib/format'
import { planPrice } from '@/lib/plans'
import {
	flagEmoji,
	hasMapCoords,
	type MapSpot,
	regionLabel,
} from '@/lib/serverMap'
import type { ComposedConfig, Plan, Profile } from '@/types/api'

export function useServerCreation() {
	const router = useRouter()
	const route = useRoute()
	const { regions, loading } = useRegions()
	const { activeTeam } = useSession()
	const { profile } = useMyProfile()
	const fleet = useServerMapData()

	// The request Central already holds for this user, if any. A teammate's creation is
	// theirs to watch, and must not take this form over. Central returns them oldest
	// first, so the last one is the request this person started most recently: watching
	// an older stuck one instead would hide the server they are actually waiting for.
	const openAction = computed(() => {
		const mine = fleet.creations.value.filter(
			(creation) => creation.requested_by === profile.value?.user,
		)
		return mine[mine.length - 1] ?? null
	})
	// Both reads must land before the form can say there is no open request, so Create
	// stays disabled until then. The fleet is a shared singleton that may still hold
	// another page's answer, so ask it again on entry.
	const openActionKnown = computed(() => fleet.loaded.value && !!profile.value)
	onMounted(() => fleet.reload())

	const operation = useProvisioningAction(activeTeam, openAction)
	const {
		action,
		submitting,
		checking,
		lastCheckedAt,
		stalled,
		error: submitError,
		retry,
		refresh: checkNow,
	} = operation
	const { canCreateServer } = useCapabilities()

	const name = ref('')
	const selectedRegion = ref<string | null>(null)

	const selectedRegionRow = computed(
		() => regions.value.find((r) => r.region === selectedRegion.value) ?? null,
	)
	// The guest OS hostname. Nothing routes by it, so the server name is enough.
	function hostnameFrom(value: string): string {
		return value
			.normalize('NFKD')
			.replace(/[\u0300-\u036f]/g, '')
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-+|-+$/g, '')
			.slice(0, 63)
			.replace(/-+$/g, '')
	}

	function selectRegion(id: string): void {
		if (!regions.value.some((r) => r.region === id)) return
		selectedRegion.value = id
	}

	// Deep link from the servers map (+ spot → ?region=), once regions load;
	// otherwise land on the first reachable region, else the first one.
	// Each distinct ?region= applies exactly once — a data reload never stomps a
	// pick the user made after landing, but a fresh in-app link still wins.
	let appliedQueryRegion = ''
	watch(
		[regions, () => route.query.region],
		([list]) => {
			if (!list.length) return
			const wanted =
				typeof route.query.region === 'string' ? route.query.region : ''
			if (
				wanted &&
				wanted !== appliedQueryRegion &&
				list.some((r) => r.region === wanted)
			) {
				appliedQueryRegion = wanted
				return selectRegion(wanted)
			}
			if (selectedRegion.value) return
			selectedRegion.value = (list.find((r) => r.reachable) ?? list[0]).region
		},
		{ immediate: true },
	)

	// The static map frames every placed region; clicking a dot
	// picks that region (0/0 coords = unplaced, listed in chips only).
	const markers = computed<MapSpot[]>(() =>
		regions.value.filter(hasMapCoords).map((r) => ({
			id: r.region,
			lat: r.latitude!,
			lng: r.longitude!,
			provider: r.provider || null,
			regionLabel: regionLabel(r),
			flag: flagEmoji(r.country_code),
		})),
	)

	// — Plan step (unchanged mechanics: presets + scoped Custom, tabs per profile).
	// A preset name, or `custom:<profile>` for a designed config in that profile.
	const {
		source,
		snapshotName,
		snapshotOptions,
		snapshotsLoading,
		snapshotsError,
		reloadSnapshots,
		offerings,
		offering,
		imageId,
		image,
		selection,
		imageOptions,
		loading: imagesLoading,
		error: imagesError,
		reload: reloadImages,
	} = useRegionalImages(
		selectedRegion,
		typeof route.query.snapshot === 'string' ? route.query.snapshot : '',
	)
	const offeringOptions = computed(() =>
		offerings.value.map((item) => ({
			label: item.title,
			value: item.name,
			logo: item.logo,
		})),
	)
	const sshKeyIds = ref<string[]>([])
	watch(activeTeam, () => {
		sshKeyIds.value = []
	})
	const hasPublicIpv6 = ref(true)
	const isFirewallEnabled = ref(false)
	watch(selection, () => {
		selectedPlan.value = null
		composedConfig.value = null
	})
	const selectedPlan = ref<string | null>(null)
	const composedConfig = ref<ComposedConfig | null>(null)
	const {
		plans,
		groups,
		classes,
		rateCard,
		profiles,
		available,
		currency,
		capacity,
		loading: plansLoading,
		error: plansError,
		reload: reloadPlans,
	} = usePlans(selectedRegion, undefined, selection)

	const canDesign = computed(
		() => rateCardComplete(rateCard.value) && profiles.value.length > 0,
	)
	const isCustom = computed(() =>
		(selectedPlan.value ?? '').startsWith('custom:'),
	)
	const selectedPlanObj = computed<Plan | null>(
		() => plans.value.find((p) => p.plan === selectedPlan.value) ?? null,
	)

	function profileFor(cls: string): Profile | null {
		return profiles.value.find((p) => p.sub_category === cls) ?? null
	}

	// Tabs when the region's presets span more than one profile; flat otherwise.
	const hasTabs = computed(() => classes.value.length > 1)
	const classTabs = computed(() =>
		classes.value.map((label) => ({ label, value: label })),
	)
	const activeTab = ref('')

	// Flat layout: the sole preset class, or General when a region offers only a designer.
	const soleClass = computed(() => classes.value[0] ?? 'General')
	const flatPresets = computed<Plan[]>(
		() => groups.value[soleClass.value] ?? [],
	)
	// Custom is only offered where the region actually prices every component (else the
	// estimate would be a $0 dead-end) — so a profile is "designable" only when canDesign.
	const flatProfile = computed<Profile | null>(() =>
		canDesign.value
			? (profileFor(soleClass.value) ??
				profiles.value.find((p) => p.sub_category === 'General') ??
				profiles.value[0] ??
				null)
			: null,
	)
	function designableProfile(cls: string): Profile | null {
		return canDesign.value ? profileFor(cls) : null
	}
	const nothingToShow = computed(
		() => !hasTabs.value && !flatPresets.value.length && !flatProfile.value,
	)

	// The cheapest config a profile can be dragged to: its smallest vCPU rung (with the
	// RAM that ratio implies) on its smallest disk rung.
	function floorConfigCost(profile: Profile): number {
		const vcpus = [...(profile.vcpu_steps ?? [])].sort((a, b) => a - b)[0] ?? 0
		const diskGb = [...(profile.disk_steps ?? [])].sort((a, b) => a - b)[0] ?? 0
		return estimateConfig(
			{
				sub_category: profile.sub_category,
				vcpus,
				memory_gb: ramFor(vcpus, profile),
				disk_gb: diskGb,
			},
			rateCard.value,
		)
	}
	const cheapestDesignCost = computed<number>(() =>
		canDesign.value && profiles.value.length
			? Math.min(...profiles.value.map(floorConfigCost))
			: Infinity,
	)

	// Tier bracket exhausted: a region is picked, no preset fits the remaining headroom
	// (the menu is already headroom-filtered server-side), and even the smallest custom
	// config is over the limit. Show a dead-end message rather than a Custom slider the
	// user can only ever drag into red.
	const availableHeadroom = computed(() => available.value ?? 0)
	const bracketExhausted = computed(
		() =>
			!!selectedRegion.value &&
			!plansLoading.value &&
			!plans.value.length &&
			canDesign.value &&
			cheapestDesignCost.value > availableHeadroom.value,
	)

	// The region itself is full: capacity gating is on and Atlas can't seat any new VM
	// right now. A capacity dead-end, not a budget one — show a distinct message (and it
	// takes priority, since there's nothing to provision here at any size).
	const regionFull = computed(
		() =>
			!!selectedRegion.value &&
			!plansLoading.value &&
			capacity.value.gated &&
			!capacity.value.available,
	)

	// Switching region re-prices the menu: reset the tab and drop a selection the new
	// region no longer offers (a preset that's gone, or a custom profile it lacks).
	watch(classes, () => {
		activeTab.value = ''
	})
	watch([plans, canDesign], () => {
		const sel = selectedPlan.value
		if (!sel) return
		if (sel.startsWith('custom:')) {
			if (!profileFor(sel.slice('custom:'.length))) selectedPlan.value = null
		} else if (!plans.value.some((p) => p.plan === sel)) {
			selectedPlan.value = null
		}
	})

	const price = computed<string | null>(() => {
		if (
			isCustom.value &&
			composedConfig.value &&
			rateCardComplete(rateCard.value)
		) {
			const monthly = estimateConfig(composedConfig.value, rateCard.value)
			return `${money(monthly, currency.value ?? 'USD', { trimTrailingZeros: true })} / mo`
		}
		return selectedPlanObj.value ? planPrice(selectedPlanObj.value) : null
	})
	const summaryResources = computed(() => {
		const config = composedConfig.value
		if (isCustom.value && config)
			return [
				{ type: 'Compute', value: `${config.vcpus}` },
				{ type: 'Memory', value: `${config.memory_gb} GB` },
				{
					type: 'Disk',
					value: `${config.disk_gb} ${rateCard.value.Disk?.unit ?? 'GB'}`,
				},
			]
		return (selectedPlanObj.value?.includes ?? [])
			.filter((inc) => inc.quantity)
			.map((inc) => ({
				type: inc.resource_type,
				value:
					inc.resource_type === 'Compute'
						? `${inc.quantity}`
						: `${inc.quantity} ${inc.unit}`,
			}))
	})
	const summary = computed(() => {
		const region = selectedRegionRow.value
		const offeringTitle = offeringOptions.value.find(
			(option) => option.value === offering.value,
		)?.label
		return {
			plan: isCustom.value
				? 'Custom'
				: selectedPlanObj.value?.title.split(' · ')[0],
			server: name.value.trim() || 'Untitled server',
			price: price.value?.split(' / ')[0] ?? '—',
			cycle: price.value?.split(' / ')[1],
			resources: summaryResources.value,
			tags: [
				region
					? `${flagEmoji(region.country_code)} ${regionLabel(region)}`
					: '',
				offeringTitle,
				[
					hasPublicIpv6.value ? 'Public IPv6' : '',
					isFirewallEnabled.value ? 'Firewall on' : '',
				]
					.filter(Boolean)
					.join(' · '),
			].filter((tag): tag is string => !!tag),
		}
	})

	const canSubmit = computed(() => {
		if (
			!canCreateServer.value ||
			!image.value ||
			imagesLoading.value ||
			plansLoading.value ||
			!!plansError.value ||
			!!action.value ||
			!openActionKnown.value ||
			!selectedRegion.value ||
			!name.value.trim()
		)
			return false
		if (regionFull.value) return false // the region can't seat a new server right now
		if (bracketExhausted.value) return false // nothing here fits the budget
		return isCustom.value ? !!composedConfig.value : !!selectedPlanObj.value
	})

	async function submit() {
		if (
			!canSubmit.value ||
			!selectedRegion.value ||
			!image.value ||
			!activeTeam.value
		)
			return
		const values = {
			team: activeTeam.value,
			region: selectedRegion.value,
			title: name.value.trim(),
			hostname: hostnameFrom(name.value),
			...selection.value,
			ssh_key_ids: sshKeyIds.value,
			has_public_ipv6: hasPublicIpv6.value,
			is_firewall_enabled: isFirewallEnabled.value,
		}
		if (isCustom.value && composedConfig.value) {
			await operation.submit('central.api.servers.create_composed_server', {
				...values,
				includes: configIncludes(composedConfig.value),
				sub_category: composedConfig.value.sub_category,
			})
		} else if (selectedPlanObj.value) {
			await operation.submit('central.api.servers.create_server', {
				...values,
				plan: selectedPlanObj.value.plan,
			})
		}
		// A lost reply still leaves the request saved in Central. Ask for it, so the
		// status panel picks it up instead of the user starting a second server.
		if (submitError.value && !action.value) fleet.reload()
	}

	function editSettings() {
		operation.reset()
	}

	// A created server belongs in the fleet, not on this form. The list opens on it.
	watch(
		() => action.value?.status,
		(status) => {
			if (status !== 'Succeeded') return
			const created = action.value?.resource_id
			operation.reset()
			router.replace({
				path: '/servers',
				query: created ? { created } : {},
			})
		},
	)

	return {
		source,
		snapshotName,
		snapshotOptions,
		snapshotsLoading,
		snapshotsError,
		reloadSnapshots,
		router,
		regions,
		loading,
		name,
		selectedRegion,
		selectedRegionRow,
		selectRegion,
		markers,
		selectedPlan,
		composedConfig,
		groups,
		rateCard,
		available,
		currency,
		capacity,
		plansLoading,
		plansError,
		reloadPlans,
		hasTabs,
		classTabs,
		activeTab,
		flatPresets,
		flatProfile,
		designableProfile,
		nothingToShow,
		regionFull,
		bracketExhausted,
		summary,
		canSubmit,
		submit,
		offering,
		offeringOptions,
		imageId,
		image,
		imageOptions,
		imagesLoading,
		imagesError,
		reloadImages,
		sshKeyIds,
		hasPublicIpv6,
		isFirewallEnabled,
		action,
		retry,
		editSettings,
		checkNow,
		checking,
		lastCheckedAt,
		stalled,
		submitting,
		submitError,
	}
}
