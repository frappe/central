// Billing-profile completeness gate, for components.
//
// A team must complete its billing profile — currency + legal name + address —
// before any money moves and before the sidebar's options unlock. This wraps the
// shared reactive store (data/billingSetup.js) the router guard also reads, scoped
// to the ACTIVE team: it (re)fetches whenever the team switcher changes teams, so
// the shell, pages, and guard always reflect the team currently in view.

import { computed, watch } from 'vue'
import { billingSetupState, fetchBillingSetup } from '@/data/billingSetup'
import { useTeam } from '@/composables/useTeam'

export function useBillingSetup() {
  const state = billingSetupState()
  const { currentTeam } = useTeam()

  // Fetch for the active team; refetch when it changes. Cached, so this is a
  // no-op once the guard has already fetched the same team.
  watch(currentTeam, (t) => { if (t) fetchBillingSetup(t) }, { immediate: true })

  return {
    complete: computed(() => !!state.data?.complete),
    missing: computed(() => state.data?.missing || []),
    currency: computed(() => state.data?.currency || null),
    currencyLocked: computed(() => !!state.data?.currency_locked),
    supportedCurrencies: computed(() => state.data?.supported_currencies || []),
    loading: computed(() => state.loading),
    reload: () => fetchBillingSetup(currentTeam.value, { force: true }),
  }
}
