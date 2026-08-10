import type { BadgeTheme } from '@/lib/status'
import type { TeamRoleRow } from '@/types/api'

export interface RoleDisplay {
	icon: string
	theme: BadgeTheme
	description: string
}

// System role name -> display (mirrors the seeded Team Role fixture's capability
// sets). Custom roles fall through to a generic display below.
const SYSTEM_ROLE_DISPLAY: Record<string, RoleDisplay> = {
	Owner: {
		icon: 'lucide-crown',
		theme: 'green',
		description: 'Full access, including billing and team',
	},
	Admin: {
		icon: 'lucide-shield',
		theme: 'orange',
		description: 'Create and manage servers, sites and services',
	},
	Developer: {
		icon: 'lucide-code-2',
		theme: 'blue',
		description: 'Create and manage servers and services',
	},
	Billing: {
		icon: 'lucide-credit-card',
		theme: 'violet',
		description: 'View and manage billing',
	},
	Viewer: {
		icon: 'lucide-eye',
		theme: 'gray',
		description: 'View-only access to servers and services',
	},
}

export function roleDisplay(role: TeamRoleRow): RoleDisplay {
	const preset = SYSTEM_ROLE_DISPLAY[role.role_name]
	if (preset) return preset

	const count = role.capabilities.length
	return {
		icon: 'lucide-shield-check',
		theme: 'violet',
		description: `${count} capabilit${count === 1 ? 'y' : 'ies'}`,
	}
}

const FALLBACK_ROLE_DISPLAY: RoleDisplay = {
	icon: 'lucide-shield-check',
	theme: 'gray',
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

// Tailwind's JIT needs literal class names (mirrors frappe-ui's Badge.vue,
// which inlines the same per-theme "subtle" classes for the same reason).
const ICON_BOX_CLASSES: Record<BadgeTheme, string> = {
	gray: 'bg-surface-gray-2 text-ink-gray-6',
	blue: 'bg-surface-blue-2 text-ink-blue-8',
	green: 'bg-surface-green-2 text-ink-green-8',
	orange: 'bg-surface-amber-2 text-ink-amber-8',
	red: 'bg-surface-red-2 text-ink-red-8',
	violet: 'bg-surface-violet-2 text-ink-violet-8',
}

export function roleIconBoxClasses(theme: BadgeTheme): string {
	return ICON_BOX_CLASSES[theme]
}

/** Avatar themes use amber where badges use orange. */
const AVATAR_THEME: Record<BadgeTheme, 'gray' | 'blue' | 'green' | 'amber' | 'red' | 'violet'> =
	{
		gray: 'gray',
		blue: 'blue',
		green: 'green',
		orange: 'amber',
		red: 'red',
		violet: 'violet',
	}

export function roleAvatarTheme(theme: BadgeTheme) {
	return AVATAR_THEME[theme]
}
