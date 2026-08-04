import { computed } from 'vue'
import { sidebarSections } from '@/components/navigation/list'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServers } from '@/composables/useServers'
import { useServerMapData } from '@/composables/useServerMapData'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useInvoices } from '@/composables/useInvoices'
import { billingPeriod } from '@/lib/date'
import { money } from '@/lib/format'

export interface SearchItem {
	name: string
	description?: string
	icon: string
	route?: string
	onSelect?: () => void | Promise<void>
}

export type SearchGroups = Record<string, { items: SearchItem[] }>

const ACTIONS: SearchItem[] = [
	{
		name: 'New server',
		description: 'Provision a server',
		icon: 'lucide-plus',
		route: '/servers/new',
	},
	{
		name: 'Invite team member',
		description: 'Send an invite',
		icon: 'lucide-user-plus',
		route: '/team/invitations',
	},
]


export function useSearchIndex() {
	const {
		canViewServers,
		canOpenServer,
		canViewBilling,
		canManageMembers,
		isMember,
	} = useCapabilities()

	const { open: openServer } = useServers()
	const { assets } = useServerMapData()
	const { members } = useTeamMembers()
	const { invoices } = useInvoices()

	return computed((): SearchGroups => {
		const groups: SearchGroups = {}

		const pages: SearchItem[] = sidebarSections.value
			.flatMap((section) => section.items)
			.filter((item) => item.condition !== false && item.to)
			.map((item) => ({
				name: item.label,
				route: item.to as string,
				icon: item.icon,
			}))

		if (pages.length) groups.Pages = { items: pages }

		const actions = ACTIONS.filter(
			(action) => action.route !== '/team/invitations' || canManageMembers.value,
		)
      
		if (actions.length) groups.Actions = { items: actions }

		if (canViewServers.value && assets.value.length) {
			groups.Servers = {
				items: assets.value.map((server) => ({
					name: server.title || server.resource_id,
					description: server.cluster,
					icon: 'lucide-server',
					onSelect: canOpenServer.value ? () => openServer(server) : undefined,
				})),
			}
		}

		if (isMember.value && members.value.length) {
			groups['Team members'] = {
				items: members.value.map((member) => ({
					name: member.full_name || member.user,
					description: member.user,
					icon: 'lucide-user',
					route: '/team/members',
				})),
			}
		}

		if (canViewBilling.value && invoices.value.length) {
			groups.Invoices = {
				items: invoices.value.map((invoice) => ({
					name: invoice.name,
					description: `${billingPeriod(invoice.period_start, invoice.period_end)} · ${money(invoice.total, invoice.currency)}`,
					icon: 'lucide-receipt',
					route: `/billing/invoices?invoice=${invoice.name}`,
				})),
			}
		}

		return groups
	})
}
