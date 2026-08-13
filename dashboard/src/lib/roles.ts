import { describeCapabilities } from '@/lib/capabilities'
import type { TeamRoleRow } from '@/types/api'

// Roles read as labels, not as a colour code: an icon carries the distinction
// and every badge stays gray, so the list has one accent — none.
export interface RoleDisplay {
	icon: string
	description: string
}

// System role name -> display (mirrors the seeded Team Role fixture's capability
// sets). Custom roles fall through to a generic display below.
const SYSTEM_ROLE_DISPLAY: Record<string, RoleDisplay> = {
	Owner: {
		icon: 'lucide-crown',
		description: 'Full access, including billing and team',
	},
	Admin: {
		icon: 'lucide-shield',
		description: 'Create and manage servers, sites and services',
	},
	Developer: {
		icon: 'lucide-code-2',
		description: 'Create and manage servers and services',
	},
	Billing: {
		icon: 'lucide-credit-card',
		description: 'View and manage billing',
	},
	Viewer: {
		icon: 'lucide-eye',
		description: 'View-only access to servers and services',
	},
}

export function roleDisplay(role: TeamRoleRow): RoleDisplay {
	const preset = SYSTEM_ROLE_DISPLAY[role.role_name]
	if (preset) return preset

	// Custom role: the description is derived from its actual grants, so it can
	// never drift from what the role does.
	return {
		icon: 'lucide-shield-check',
		description: describeCapabilities(role.capabilities),
	}
}

const FALLBACK_ROLE_DISPLAY: RoleDisplay = {
	icon: 'lucide-shield-check',
	description: '',
}

/** Look up a member's role (by doc name) in the team's role list for its display. */
export function roleDisplayByName(
	roles: TeamRoleRow[],
	roleName: string,
): RoleDisplay {
	const role = roles.find((r) => r.name === roleName)
	return role ? roleDisplay(role) : FALLBACK_ROLE_DISPLAY
}
