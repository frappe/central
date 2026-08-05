import { useCall } from 'frappe-ui'
import { computed, type Ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import type {
	Capacity,
	Plan,
	Profile,
	ProvisionablePlans,
	RateCard,
} from '@/types/api'

// Ungated fallback while the menu is loading (or on a resize, which isn't capacity-gated).
const UNGATED: Capacity = {
	gated: false,
	available: true,
	unmeasured: false,
	largest_vm: null,
}

// Plans a team can provision in the selected region, from the billing catalog
// (central.billing.api.dashboard.catalog.get_eligible_plans). The menu is
// already narrowed server-side: priced for the team's currency on that region,
// admitted by the trust tier's allow-lists, and within the team's remaining
// trust-tier headroom (spend cap minus current run-rate). Plans are priced and
// gated per region, so this refetches whenever the picked region changes — and
// stays empty until a region is picked (no cluster, nothing to price).

export function usePlans(
	cluster: Ref<string | null>,
	excludeSubscription?: Ref<string | null>,
) {
	const { activeTeam } = useSession()

	// When resizing, `excludeSubscription` frees the resized server's own spend back
	// into the headroom the menu is filtered by (so it can grow into its own budget).
	const call = useCall<
		ProvisionablePlans,
		{ team: string; cluster: string; exclude_subscription?: string }
	>({
		url: method(API.eligiblePlans),
		params: () => ({
			team: activeTeam.value!,
			cluster: cluster.value!,
			...(excludeSubscription?.value
				? { exclude_subscription: excludeSubscription.value }
				: {}),
		}),
		immediate: false,
	})

	watch(
		[activeTeam, cluster, () => excludeSubscription?.value],
		([team, region]) => {
			if (team && region) call.reload()
		},
		{ immediate: true },
	)

	// The menu arrives grouped by plan class (keys ordered, rows cheapest-first);
	// `classes` is the tab order, `plans` a flat view for selection lookups.
	const groups = computed<Record<string, Plan[]>>(() => call.data?.plans ?? {})

	return {
		groups,
		classes: computed<string[]>(() => Object.keys(groups.value)),
		plans: computed<Plan[]>(() => Object.values(groups.value).flat()),
		currency: computed<string | null>(() => call.data?.currency ?? null),
		tier: computed<string | null>(() => call.data?.tier ?? null),
		// Remaining trust-tier headroom in the team's currency — explains an empty menu.
		available: computed<number | null>(() => call.data?.available ?? null),
		// "Design your own" inputs: the per-resource rate card + the profile bounds.
		rateCard: computed<RateCard>(() => call.data?.rate_card ?? {}),
		profiles: computed<Profile[]>(() => call.data?.profiles ?? []),
		// Live provisioning capacity for this region: caps the custom slider and explains an
		// empty menu when the region is full (`available` false).
		capacity: computed<Capacity>(() => call.data?.capacity ?? UNGATED),
		// Loading until the response *echo* matches the picked region — the fetch
		// starts a tick after `cluster` changes, and without this gate the previous
		// region's menu flashes through in that gap.
		loading: computed(
			() =>
				call.loading ||
				(!!cluster.value && call.data?.cluster !== cluster.value),
		),
	}
}
