import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import type { Team } from '@/types/api'

// Identity for the console: which teams the signed-in user belongs to, and which
// one is active. Module-level singletons so every screen + composable scopes its
// reads (registry, capabilities) to the same team, and a single switch re-drives
// all of them. The active team is persisted so a refresh keeps your context.

const STORAGE_KEY = 'central.console.activeTeam'

function storedTeam(): string | null {
	try {
		return localStorage.getItem(STORAGE_KEY)
	} catch {
		return null
	}
}

const activeTeam = ref<string | null>(storedTeam())

function selectTeam(name: string | null) {
	activeTeam.value = name
	try {
		if (name) localStorage.setItem(STORAGE_KEY, name)
	} catch {
		/* storage unavailable (private mode) — in-memory selection still works */
	}
}

const teamsCall = useCall<Team[]>({
	url: method(API.myTeams),
	// Settle the active team once we know the roster: keep a valid stored choice,
	// otherwise fall back to the first team. (my_teams takes no args.)
	onSuccess: (teams: Team[]) => {
		const names = teams.map((t) => t.name)
		if (!activeTeam.value || !names.includes(activeTeam.value)) {
			selectTeam(teams[0]?.name ?? null)
		}
	},
})

// Resolves once my_teams has settled the active team. Router + team-scoped reads
// await this so atlas/iam calls never fire with a missing team (multi-team users
// get "Specify a team." from central.iam.resolve_team).
export const sessionReady = teamsCall.promise

export function useSession() {
	return {
		teams: computed<Team[]>(() => teamsCall.data ?? []),
		loading: computed(() => teamsCall.loading),
		activeTeam,
		activeTeamLabel: computed(
			() =>
				(teamsCall.data ?? []).find((t) => t.name === activeTeam.value)
					?.label ?? 'Central',
		),
		setActiveTeam: selectTeam,
		reload: () => teamsCall.reload(),
	}
}
