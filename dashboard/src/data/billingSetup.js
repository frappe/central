// Billing-profile completeness for the ACTIVE team — one shared, reactive,
// cached source of truth.
//
// Both the router onboarding guard (which AWAITS it before a route renders) and
// the shell/pages (which REACT to it — sidebar lock, banners) read this single
// store, so they never drift. It is keyed on the team it was fetched for: when
// the team switcher changes the active team, the next fetch re-checks THAT team
// (not the user's default). After the profile is saved, force-refetch and every
// consumer updates at once.

import { reactive } from 'vue'
import { API, m } from '@/api/endpoints'

const state = reactive({ data: null, loading: false, team: undefined })
let inflight = null

export function billingSetupState() {
  return state
}

// `team` scopes the check; '' (or falsy) lets the backend resolve the caller's
// default team. Cached per-team, so a team switch refetches.
export async function fetchBillingSetup(team, { force = false } = {}) {
  const key = team || ''
  if (!force && state.team === key && state.data != null) return state.data
  if (force || state.team !== key) inflight = null
  if (!inflight) {
    inflight = (async () => {
      state.loading = true
      try {
        const base = m(API.billingSetup)
        const url = key ? `${base}?team=${encodeURIComponent(key)}` : base
        const r = await fetch(url, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        })
        const j = r.ok ? await r.json() : null
        state.data = j ? j.data ?? j.message ?? j : null
        state.team = key
      } catch {
        state.data = null // fail-open: the guard won't trap anyone if this errors
        state.team = key
      } finally {
        state.loading = false
        inflight = null
      }
    })()
  }
  await inflight
  return state.data
}

export function invalidateBillingSetup() {
  state.team = undefined
}
