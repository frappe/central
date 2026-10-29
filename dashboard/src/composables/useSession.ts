import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import type { Team } from '@/types/api'

const STORAGE_KEY = 'central.console.activeTeam'
const IMPERSONATION_KEY = 'central.console.viewAs'

function storedTeam(): string | null {
	try {
		return localStorage.getItem(STORAGE_KEY)
	} catch {
		return null
	}
}

// A System Manager opens the console as a team owner from Desk with ?view_as=<team>.
// It lives for this tab only, so the operator's own stored team stays untouched.
function readImpersonatedTeam(): string | null {
	const url = new URL(window.location.href)
	const team = url.searchParams.get('view_as')
	if (team) {
		url.searchParams.delete('view_as')
		window.history.replaceState(window.history.state, '', url)
	}
	try {
		if (team) sessionStorage.setItem(IMPERSONATION_KEY, team)
		return sessionStorage.getItem(IMPERSONATION_KEY)
	} catch {
		return team
	}
}

function clearImpersonation(): void {
	try {
		sessionStorage.removeItem(IMPERSONATION_KEY)
	} catch {
		/* storage unavailable: the impersonation ends with the page */
	}
}

const impersonatedTeam = readImpersonatedTeam()
const activeTeam = ref<string | null>(impersonatedTeam ?? storedTeam())

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
	if (impersonatedTeam && name !== impersonatedTeam) clearImpersonation()

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

const teamsCall = useCall<Team[], { view_as?: string }>({
	url: method(API.myTeams),
	params: () => (impersonatedTeam ? { view_as: impersonatedTeam } : {}),
	// Settle the active team once we know the roster: keep a valid stored choice,
	// otherwise fall back to the first team.
	onSuccess: (teams: Team[]) => {
		const names = teams.map((t) => t.name)
		if (impersonatedTeam && !names.includes(impersonatedTeam))
			clearImpersonation()
		if (!activeTeam.value || !names.includes(activeTeam.value)) {
			const usable = teams.find((team) => team.status === 'Active') ?? teams[0]
			selectTeam(usable?.name ?? null)
		}
	},
})

/** Leave the impersonated team and go back to it in Desk. */
function endImpersonation(): void {
	clearImpersonation()
	window.location.assign(
		`/desk/team/${encodeURIComponent(impersonatedTeam ?? '')}`,
	)
}

/** Select a team the caller just created. No page has read another team's data yet. */
async function adoptNewTeam(name: string): Promise<void> {
	selectTeam(name)
	await teamsCall.reload()
}

// Resolves once my_teams has settled the active team. Router + team-scoped reads
// await this so atlas/iam calls never fire with a missing team (multi-team users
// get "Specify a team." from central.iam.resolve_team).
export const sessionReady = teamsCall.promise

export function useSession() {
	return {
		teams: computed<Team[]>(() => teamsCall.data ?? []),
		loading: computed(() => teamsCall.loading),
		error: computed(() => teamsCall.error),
		// False until my_teams answers, so "no teams" is never read from a pending call.
		isLoaded: computed(() => teamsCall.data != null),
		activeTeam,
		activeTeamLabel: computed(
			() =>
				(teamsCall.data ?? []).find((t) => t.name === activeTeam.value)
					?.label ?? 'Frappe Cloud',
		),
		activeTeamLogo: computed(
			() =>
				(teamsCall.data ?? []).find((t) => t.name === activeTeam.value)?.logo ??
				null,
		),
		impersonatedTeam: computed(
			() =>
				(teamsCall.data ?? []).find(
					(t) => t.is_impersonated && t.name === activeTeam.value,
				) ?? null,
		),
		isActiveTeamSuspended: computed(
			() =>
				(teamsCall.data ?? []).find((t) => t.name === activeTeam.value)
					?.status === 'Suspended',
		),
		endImpersonation,
		setActiveTeam: switchTeam,
		adoptNewTeam,
		reload: () => teamsCall.reload(),
	}
}
