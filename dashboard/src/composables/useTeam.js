// Active-team scope, shared across every screen.
//
// Default scope is the signed-in user's own team (from whoami). A user can switch
// to another team they belong to; a System Manager (operator) can impersonate ANY
// team. The choice persists, but is bound to the user who made it — an override
// from a different session is ignored, so a stale stored team can never scope the
// dashboard to a team the current user can't access (the old blank-dashboard bug).
//
// Before whoami resolves, currentTeam is '' — the billing endpoints treat an empty
// team as "resolve my default", so the first reads still land correctly.

import { ref, computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'

const STORAGE_KEY = 'central.activeTeam' // { user, team }

const who = useCall({ url: m(API.whoami) })

// The initial whoami request; resolves once identity (and thus currentTeam) is
// known. The router guard awaits this so it gates billing setup on the ACTIVE
// team, not an empty/default one. Holds a stable reference to the first promise,
// which stays resolved — awaiting it later is a no-op.
export const whoReady = who.promise

function loadOverride() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
  } catch {
    return null
  }
}
const override = ref(loadOverride())

// The override only counts for the session that set it.
const currentTeam = computed(() => {
  const ov = override.value
  if (ov && who.data && ov.user === who.data.user && ov.team) return ov.team
  return who.data?.team || ''
})

function setTeam(name) {
  const user = who.data?.user
  if (name && user) {
    override.value = { user, team: name }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(override.value))
  } else {
    override.value = null
    localStorage.removeItem(STORAGE_KEY)
  }
}

export function useTeam() {
  return {
    currentTeam,
    setTeam,
    who,
    homeTeam: computed(() => who.data?.team || ''),
    isOperator: computed(() => who.data?.is_operator ?? false),
  }
}
