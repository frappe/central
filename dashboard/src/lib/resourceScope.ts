import type {
	ResourceType,
	TeamMemberRoleAssignment,
	TeamRegistry,
} from '@/types/api'

/** Short label for where a role grant applies. */
export function resourceScopeLabel(
	grant: Pick<TeamMemberRoleAssignment, 'resource_type' | 'resource_name'>,
	registry?: TeamRegistry | null,
): string {
	if (grant.resource_type === '*' || !grant.resource_name)
		return 'All resources'

	if (registry) {
		if (grant.resource_type === 'Server') {
			const asset = registry.assets.find((a) => a.name === grant.resource_name)
			if (asset) return asset.title || asset.resource_id
		}
		if (grant.resource_type === 'Site') {
			const site = registry.sites.find((s) => s.name === grant.resource_name)
			if (site) return site.subdomain || site.name
		}
	}

	return grant.resource_name
}

export function resourceTypeIcon(type: ResourceType): string {
	switch (type) {
		case 'Server':
			return 'lucide-server'
		case 'Site':
			return 'lucide-globe'
		case '*':
			return 'lucide-layers'
		default: {
			const _exhaustive: never = type
			return _exhaustive
		}
	}
}

/** Compact badge text: "Developer · All resources". */
export function roleOnResourceLabel(
	roleLabel: string,
	grant: Pick<TeamMemberRoleAssignment, 'resource_type' | 'resource_name'>,
	registry?: TeamRegistry | null,
): string {
	return `${roleLabel} · ${resourceScopeLabel(grant, registry)}`
}
