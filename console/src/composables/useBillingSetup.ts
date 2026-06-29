// Billing-profile completeness gate, for components (ported from the legacy
// dashboard's composables/useBillingSetup.js).
//
// A team must complete its billing profile — currency + legal name + address —
// before any money moves. Navigation stays open even when it's incomplete; what's
// gated are the money-moving actions (top-up, credits, add payment method), via
// requireSetup(). This wraps the shared reactive store (data/billingSetup.ts)
// scoped to the ACTIVE team: it (re)fetches whenever the team switcher changes,
// so the shell and pages always reflect the team currently in view.

import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { billingSetupState, fetchBillingSetup, invalidateBillingSetup } from '@/data/billingSetup'
import { useSession } from '@/composables/useSession'
import { infoToast } from '@/lib/toast'

const BILLING_ONBOARDING = '/billing/onboarding'

export function useBillingSetup() {
  const state = billingSetupState()
  const { activeTeam } = useSession()
  const router = useRouter()
  const route = useRoute()

  // Fetch for the active team; refetch when it changes. Cached, so this is a
  // no-op once the guard has already warmed the same team.
  watch(activeTeam, (t) => { if (t) fetchBillingSetup(t) }, { immediate: true })

  // Call at the start of a money-moving action. If the profile is incomplete it
  // diverts the user to onboarding (remembering where they were) and returns
  // false so the caller bails out; returns true when it's safe to proceed.
  function requireSetup(): boolean {
    if (state.data?.complete) return true
    infoToast('Complete your billing setup to continue.')
    router.push({ path: BILLING_ONBOARDING, query: { redirect: route.fullPath } })
    return false
  }

  // After saving the profile, re-pull so every consumer reflects the new state.
  async function refresh(): Promise<void> {
    invalidateBillingSetup()
    await fetchBillingSetup(activeTeam.value, { force: true })
  }

  return {
    complete: computed(() => !!state.data?.complete),
    missing: computed(() => state.data?.missing ?? []),
    currency: computed(() => state.data?.currency ?? null),
    currencyLocked: computed(() => !!state.data?.currency_locked),
    supportedCurrencies: computed(() => state.data?.supported_currencies ?? []),
    loading: computed(() => state.loading),
    profile: computed(() => state.data),
    requireSetup,
    refresh,
    // Legacy alias — force a re-pull of the shared state.
    reload: refresh,
  }
}
