// Single-team scope, shared across every screen. With no team switcher, the
// active team is simply the logged-in user's own team, straight from whoami —
// authoritative and never persisted. (Persisting it caused a stale team to stick
// across logins in the same browser, scoping calls to a team the new user can't
// access → a blank dashboard.)
//
// Before whoami resolves, currentTeam is '' — the billing endpoints treat an
// empty team as "resolve my default team", so the first reads still land on the
// right data without a flicker.

import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'

const who = useCall({ url: m(API.whoami) })

const currentTeam = computed(() => who.data?.team || '')

export function useTeam() {
  return {
    currentTeam,
    who,
    isOperator: computed(() => who.data?.is_operator ?? false),
  }
}
