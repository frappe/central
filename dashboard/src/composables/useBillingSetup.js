// Billing-profile completeness gate, for components.
//
// A team must complete its billing profile — currency + legal name + address —
// before any money moves. Navigation is open even when it's incomplete; what's
// gated are the money-moving actions (top-up, credits, payment method), via
// requireSetup() below. This wraps the shared reactive store (data/billingSetup.js)
// scoped to the ACTIVE team: it (re)fetches whenever the team switcher changes
// teams, so the shell and pages always reflect the team currently in view.

import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { billingSetupState, fetchBillingSetup } from '@/data/billingSetup'
import { useTeam } from '@/composables/useTeam'
import { infoToast } from '@/utils/toast'

export function useBillingSetup() {
  const state = billingSetupState()
  const { currentTeam } = useTeam()
  const router = useRouter()
  const route = useRoute()

  // Fetch for the active team; refetch when it changes. Cached, so this is a
  // no-op once the guard has already fetched the same team.
  watch(currentTeam, (t) => { if (t) fetchBillingSetup(t) }, { immediate: true })

  // Call at the start of a money-moving action. If the profile is incomplete it
  // diverts the user to onboarding (remembering where they were) and returns
  // false so the caller bails out; returns true when it's safe to proceed.
  function requireSetup() {
    if (state.data?.complete) return true
    infoToast('Complete your billing setup to continue.')
    router.push({ path: '/onboarding', query: { redirect: route.fullPath } })
    return false
  }

  return {
    complete: computed(() => !!state.data?.complete),
    missing: computed(() => state.data?.missing || []),
    currency: computed(() => state.data?.currency || null),
    currencyLocked: computed(() => !!state.data?.currency_locked),
    supportedCurrencies: computed(() => state.data?.supported_currencies || []),
    loading: computed(() => state.loading),
    reload: () => fetchBillingSetup(currentTeam.value, { force: true }),
    requireSetup,
  }
}
