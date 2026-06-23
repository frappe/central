import { computed, watch, type Ref } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import type { Plan, ProvisionablePlans } from '@/types'

// Plans a team can provision in the selected region, from the billing catalog
// (central.billing.api.dashboard.catalog.get_eligible_plans). The menu is
// already narrowed server-side: priced for the team's currency on that region,
// admitted by the trust tier's allow-lists, and within the team's remaining
// trust-tier headroom (spend cap minus current run-rate). Plans are priced and
// gated per region, so this refetches whenever the picked region changes — and
// stays empty until a region is picked (no cluster, nothing to price).

export function usePlans(cluster: Ref<string | null>) {
  const { activeTeam } = useSession()

  const call = useCall<ProvisionablePlans, { team: string; cluster: string }>({
    url: method(API.eligiblePlans),
    params: () => ({ team: activeTeam.value!, cluster: cluster.value! }),
    immediate: false,
  })

  watch(
    [activeTeam, cluster],
    ([team, region]) => {
      if (team && region) call.reload()
    },
    { immediate: true },
  )

  return {
    plans: computed<Plan[]>(() => call.data?.plans ?? []),
    currency: computed<string | null>(() => call.data?.currency ?? null),
    tier: computed<string | null>(() => call.data?.tier ?? null),
    // Remaining trust-tier headroom in the team's currency — explains an empty menu.
    available: computed<number | null>(() => call.data?.available ?? null),
    loading: computed(() => call.loading),
  }
}
