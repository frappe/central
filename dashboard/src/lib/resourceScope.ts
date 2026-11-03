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
			const server = registry.servers.find(
				(s) => s.name === grant.resource_name,
			)
			if (server) return server.title || server.resource_id
		}
		if (grant.resource_type === 'Site') {
			const site = registry.sites.find((s) => s.name === grant.resource_name)
			if (site) return site.subdomain || site.name
		}
	}

	return grant.resource_name
}

export interface ResourceOption {
	label: string
	/** `Type::name`, or `*::` for every resource. */
	value: string
	description?: string
}

/** What a role grant can apply to. A server that runs a site is offered as that site,
 *  which stands for its machine, unless a grant in `selected` already names the server. */
export function getResourceOptions(
	registry: TeamRegistry | null | undefined,
	regionLabel: (region: string) => string | undefined,
	selected: string[] = [],
): ResourceOption[] {
	const sites = registry?.sites ?? []
	const siteServers = new Set(sites.map((site) => site.server))
	const servers = (registry?.servers ?? []).filter(
		(server) =>
			!siteServers.has(server.name) ||
			selected.includes(`Server::${server.name}`),
	)

	return [
		{ label: 'All resources', value: '*::' },
		...servers.map((server) => ({
			label: server.title || server.resource_id,
			value: `Server::${server.name}`,
			description: regionLabel(server.region),
		})),
		...sites.map((site) => ({
			label: site.subdomain || site.name,
			value: `Site::${site.name}`,
			description: regionLabel(site.region),
		})),
	]
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
