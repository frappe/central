import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import type { Team } from '@/types'

// Identity for the console: which teams the signed-in user belongs to, and which
// one is active. Module-level singletons so every screen + composable scopes its
// reads (registry, capabilities) to the same team. A full team switcher is out of
// scope for now — we default to the first team; `setActiveTeam` is ready for when
// a switcher lands.

const activeTeam = ref<string | null>(null)

const teamsCall = useCall<Team[]>({
  url: method(API.myTeams),
  // my_teams takes no args; default the active team to the first one we get.
  onSuccess: (teams: Team[]) => {
    if (!activeTeam.value && teams.length) activeTeam.value = teams[0].name
  },
})

export function useSession() {
  return {
    teams: computed<Team[]>(() => teamsCall.data ?? []),
    loading: computed(() => teamsCall.loading),
    activeTeam,
    activeTeamLabel: computed(
      () => (teamsCall.data ?? []).find((t) => t.name === activeTeam.value)?.label ?? 'Central',
    ),
    setActiveTeam(name: string) {
      activeTeam.value = name
    },
    reload: () => teamsCall.reload(),
  }
}
