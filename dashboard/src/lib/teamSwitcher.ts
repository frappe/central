import type { Team } from '@/types/api'

export interface TeamSwitcherRow extends Team {
	detail: string
	identity: string
}

/** Distinguish matching team names without changing their stored labels. */
export function getTeamSwitcherRows(teams: Team[]): TeamSwitcherRow[] {
	const groups = new Map<string, Team[]>()
	for (const team of teams) {
		const label = team.label.trim().toLocaleLowerCase()
		groups.set(label, [...(groups.get(label) ?? []), team])
	}

	return teams.map((team) => {
		const matches = groups.get(team.label.trim().toLocaleLowerCase())!
		const hasUniqueOwner =
			team.owner &&
			matches.filter((match) => match.owner === team.owner).length === 1
		const owner =
			matches.length > 1 ? (hasUniqueOwner ? team.owner! : team.name) : ''
		const detail = [owner, team.status === 'Suspended' ? 'Suspended' : '']
			.filter(Boolean)
			.join(' · ')
		return {
			...team,
			detail,
			identity: detail ? `${team.label} · ${detail}` : team.label,
		}
	})
}
