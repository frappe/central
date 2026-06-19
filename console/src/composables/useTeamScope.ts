import { watch } from 'vue'
import { useSession } from '@/composables/useSession'

const { activeTeam } = useSession()

/** Query/body params for team-scoped atlas + iam reads. */
export function teamParams(): { team: string } {
  return { team: activeTeam.value! }
}

/** Don't hit the network until my_teams has picked an active team. */
export function whenTeamReady(reload: () => unknown): void {
  watch(
    activeTeam,
    (team) => {
      if (team) reload()
    },
    { immediate: true },
  )
}
