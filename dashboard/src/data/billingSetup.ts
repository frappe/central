// Billing-profile completeness for the ACTIVE team — one shared, reactive,
// cached source of truth (ported from the legacy dashboard's data/billingSetup.js).
//
// Both the router guard (which warms this before a route renders) and the shell /
// pages (which REACT to it — action gating, banners) read this single store, so
// they never drift. It is keyed on the team it was fetched for: a team switch
// re-checks THAT team. After the profile is saved, force-refetch and every
// consumer updates at once.
//
// Raw fetch (not useCall) on purpose: the guard must AWAIT a fresh result for a
// specific team, and the store keeps its own per-team cache + imperative
// invalidation — control useCall's reactive-params model doesn't give us cleanly.
// It's a GET read, so the useCall-GET-write-rollback caveat doesn't apply.

import { reactive } from 'vue'
import { API, method } from '@/api/methods'
import type { BillingProfile } from '@/types/billing'

interface SetupState {
  data: BillingProfile | null
  loading: boolean
  team: string | undefined
}

const state = reactive<SetupState>({ data: null, loading: false, team: undefined })
let inflight: Promise<void> | null = null

export function billingSetupState(): SetupState {
  return state
}

// `team` scopes the check; '' (or falsy) lets the backend resolve the caller's
// default team. Cached per-team, so a team switch refetches.
export async function fetchBillingSetup(
  team: string | null | undefined,
  { force = false }: { force?: boolean } = {},
): Promise<BillingProfile | null> {
  const key = team || ''
  if (!force && state.team === key && state.data != null) return state.data
  if (force || state.team !== key) inflight = null
  if (!inflight) {
    inflight = (async () => {
      state.loading = true
      try {
        const base = method(API.billingProfile)
        const url = key ? `${base}?team=${encodeURIComponent(key)}` : base
        const r = await fetch(url, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        })
        const j = r.ok ? await r.json() : null
        state.data = j ? (j.data ?? j.message ?? j) : null
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

export function invalidateBillingSetup(): void {
  state.team = undefined
}
