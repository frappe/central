// Current-team scope, shared across every screen. Multi-team users pick the
// active team here; all billing endpoints auto-scope to it server-side. The UI
// never sends a team as authority — passing another team's name 403s (IDOR).

import { ref, computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'

const STORAGE_KEY = 'central.currentTeam'

const currentTeam = ref(localStorage.getItem(STORAGE_KEY) || null)

// Teams the signed-in user can switch between (POC: teams with billing data).
const teams = useCall({ url: m(API.switchableTeams) })

const who = useCall({
  url: m(API.whoami),
  onSuccess: (data) => {
    // Default to the caller's own team the first time, if nothing is stored.
    if (!currentTeam.value && data?.team) setTeam(data.team)
  },
})

function setTeam(name) {
  currentTeam.value = name
  if (name) localStorage.setItem(STORAGE_KEY, name)
  else localStorage.removeItem(STORAGE_KEY)
}

export function useTeam() {
  return {
    currentTeam,
    setTeam,
    teams,
    who,
    isOperator: computed(() => who.data?.is_operator ?? false),
  }
}
