import { useColorScheme } from 'frappe-ui'
import { computed } from 'vue'
import { sidebarSections } from '@/components/navigation/list'
import { useAppMenu } from '@/composables/useAppMenu'
import { useCapabilities } from '@/composables/useCapabilities'
import { useInvoices } from '@/composables/useInvoices'
import { useServerMapData } from '@/composables/useServerMapData'
import { useServers } from '@/composables/useServers'
import { openSettings } from '@/composables/useSettings'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { billingPeriod } from '@/lib/date'
import { money } from '@/lib/format'

export interface SearchItem {
	name: string
	description?: string
	icon: string
	route?: string
	onSelect?: () => void | Promise<void>
}

export type SearchGroups = Record<
	string,
	{ items: SearchItem[]; searchOnly?: boolean }
>

export function useSearchIndex() {
	const {
		canCreateServer,
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
	const { themeOptions } = useAppMenu()
	const { setColorScheme } = useColorScheme()

	return computed((): SearchGroups => {
		// Insertion order is the display order: verbs first, then destinations.
		const groups: SearchGroups = {}

		const actions: SearchItem[] = []

		// The invoice you'd actually come here for — the newest one still owing.
		// list_invoices is newest-first, so the first unsettled row is it.
		const owing = invoices.value.find(
			(inv) => !['paid', 'void'].includes(String(inv.status).toLowerCase()),
		)
		if (canViewBilling.value && owing) {
			actions.push({
				name: 'Current invoice',
				description: `${billingPeriod(owing.period_start, owing.period_end)} · ${money(owing.total, owing.currency)}`,
				icon: 'lucide-receipt',
				route: `/billing/invoices?invoice=${owing.name}`,
			})
		}
		if (canCreateServer.value) {
			actions.push({
				name: 'New server',
				description: 'Provision a server',
				icon: 'lucide-plus',
				route: '/servers/new',
			})
		}
		if (canManageMembers.value) {
			actions.push({
				name: 'Invite team member',
				description: 'Send an invite',
				icon: 'lucide-user-plus',
				route: '/team/members',
			})
		}
		actions.push({
			name: 'Switch team',
			icon: 'lucide-repeat',
			onSelect: () => openSettings('teams'),
		})

		if (actions.length) groups.Actions = { items: actions }

		const pages: SearchItem[] = sidebarSections.value
			.flatMap((section) => section.items)
			.filter((item) => item.condition !== false && item.to)
			.map((item) => ({
				name: item.label,
				route: item.to as string,
				icon: item.icon,
			}))

		if (pages.length) groups.Pages = { items: pages }

		groups.Theme = {
			items: themeOptions.map((theme) => ({
				name: theme.label,
				icon: theme.icon,
				onSelect: () => setColorScheme(theme.value),
			})),
		}

		// Records, not menu entries: searchable, but they'd bury the verbs above
		// if the whole fleet/roster/ledger listed on every open.
		if (canViewServers.value && assets.value.length) {
			groups.Servers = {
				searchOnly: true,
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
				searchOnly: true,
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
				searchOnly: true,
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
