// Billing-profile completeness gate, for components.
//
// A team must complete its billing profile — currency + legal name + address —
// before any money moves. Navigation stays open even when it's incomplete; what's
// gated are the money-moving actions (top-up, credits, add payment method), via
// requireSetup(). This wraps the shared reactive store (data/billingSetup.ts)
// scoped to the ACTIVE team: it (re)fetches whenever the team switcher changes,
// so the shell and pages always reflect the team currently in view.
//
// There is no separate onboarding page anymore — the billing profile is filled
// inline from the Overview's "Billing contact & tax" card. So requireSetup just
// opens that edit dialog (shared via setupDialogOpen) instead of redirecting.

import { computed, ref, watch } from 'vue'
import { useSession } from '@/composables/useSession'
import {
	billingSetupState,
	fetchBillingSetup,
	invalidateBillingSetup,
} from '@/data/billingSetup'

// Module-level so a money-moving action anywhere can ask the Overview to open its
// billing-profile edit dialog, and the dialog reflects that one source of truth.
const setupDialogOpen = ref(false)

export function useBillingSetup() {
	const state = billingSetupState()
	const { activeTeam } = useSession()

	// Fetch for the active team; refetch when it changes. Cached, so this is a
	// no-op once the guard has already warmed the same team.
	watch(
		activeTeam,
		(t) => {
			if (t) fetchBillingSetup(t)
		},
		{ immediate: true },
	)

	// Call at the start of a money-moving action. If the profile is incomplete it
	// opens the billing-details dialog and returns false so the caller bails out;
	// returns true when it's safe to proceed. No toast: the dialog opens in place
	// and explains itself — a caller that redirects across pages instead should
	// show its own explanation (see NewServerPage.submit).
	function requireSetup(): boolean {
		if (state.data?.complete) return true
		setupDialogOpen.value = true
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
		// Whether the billing-profile edit dialog should be open (shared).
		setupDialogOpen,
		requireSetup,
		refresh,
		// Legacy alias — force a re-pull of the shared state.
		reload: refresh,
	}
}
