import { watch } from 'vue'
import { useSession } from '@/composables/useSession'

const { activeTeam } = useSession()

/** Query/body params for team-scoped atlas + iam reads. */
export function teamParams(): { team: string } {
	return { team: activeTeam.value! }
}

/**
 * Kick a team-scoped useCall once an active team exists.
 *
 * Callers pair this with `immediate: false` + `refetch: true`: this covers the
 * initial settle (null → team), and `refetch` re-runs on later team switches via
 * the reactive params/URL. Reloading here on every switch would race the refetch
 * and surface a transient AbortError ("signal is aborted").
 */
export function whenTeamReady(reload: () => unknown): void {
	watch(
		activeTeam,
		(team, previous) => {
			if (!team) return
			if (previous === undefined || previous === null) reload()
		},
		{ immediate: true },
	)
}
