import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import type { Team } from '@/types/api'

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
		else localStorage.removeItem(STORAGE_KEY)
	} catch {
		/* storage unavailable (private mode) — in-memory selection still works */
	}
}

function switchTeam(name: string | null): void {
	if (name === activeTeam.value) return

	try {
		if (name) localStorage.setItem(STORAGE_KEY, name)
		else localStorage.removeItem(STORAGE_KEY)
	} catch {
		throw new Error(
			'Could not save the selected team. Allow browser storage and try again.',
		)
	}

	const path = window.location.pathname
	if (
		path.startsWith('/dashboard/servers/') &&
		path !== '/dashboard/servers/snapshots'
	) {
		window.location.replace('/dashboard/servers')
	} else if (path.startsWith('/dashboard/object-storage/')) {
		window.location.replace('/dashboard/object-storage')
	} else {
		window.location.reload()
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

const activeTeamEntry = computed(() =>
	(teamsCall.data ?? []).find((t) => t.name === activeTeam.value),
)

export function useSession() {
	return {
		teams: computed<Team[]>(() => teamsCall.data ?? []),
		loading: computed(() => teamsCall.loading),
		error: computed(() => teamsCall.error),
		// False until my_teams answers, so "no teams" is never read from a pending call.
		isLoaded: computed(() => teamsCall.data != null),
		activeTeam,
		activeTeamLabel: computed(
			() => activeTeamEntry.value?.label ?? 'Frappe Cloud',
		),
		activeTeamLogo: computed(() => activeTeamEntry.value?.logo ?? null),
		/** The partner the user works for on the active team, when it is one of its clients. */
		activePartner: computed(() => activeTeamEntry.value?.via_partner ?? null),
		isPartnerTeam: computed(() => activeTeamEntry.value?.is_partner ?? false),
		setActiveTeam: switchTeam,
		reload: () => teamsCall.reload(),
	}
}
