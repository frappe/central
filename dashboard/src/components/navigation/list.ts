import { type Component, computed, defineAsyncComponent } from 'vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useIsMobile } from '@/composables/useIsMobile'
import { openSearch } from '@/composables/useSearch'
import { features } from '@/lib/features'

const NotificationsPanel = defineAsyncComponent(
	() => import('@/components/notifications/NotificationsPanel.vue'),
)

type SidebarItem = {
	label: string
	icon: string
	to?: string
	condition?: boolean
	class?: string
	onClick?: () => void
	component?: Component
}

type SidebarSection = {
	label: string
	collapsible?: boolean
	items: SidebarItem[]
}

export const sidebarSections = computed<SidebarSection[]>(() => {
	const isMobile = useIsMobile()

	const { canViewServers, canViewBilling, canViewServices, isMember } =
		useCapabilities()

	return [
		{
			label: '',
			items: [
				{
					label: 'Search',
					icon: 'lucide-search',
					onClick: openSearch,
					condition: !isMobile.value,
				},
				{
					label: 'Notifications',
					icon: 'lucide-bell',
					condition: isMember.value && !isMobile.value,
					component: NotificationsPanel,
				},
			],
		},

		{
			label: '',
			items: [
				{
					label: 'Servers',
					icon: 'lucide-server',
					to: '/servers',
					condition: canViewServers.value,
				},
				{
					label: 'Services',
					icon: 'lucide-blocks',
					to: '/addons',
					condition: features.addons && canViewServices.value,
				},
				// The sent-invitations page (/team/invitations) still exists but has
				// no sidebar entry — pending invites are managed from the Team page.
				{
					label: 'Team',
					icon: 'lucide-users',
					to: '/team/members',
					condition: isMember.value,
				},
			],
		},

		{
			label: 'Billing',
			items: [
				{
					label: 'Overview',
					icon: 'lucide-credit-card',
					to: '/billing',
					condition: canViewBilling.value,
				},
				{
					label: 'Invoices',
					icon: 'lucide-receipt',
					to: '/billing/invoices',
					condition: canViewBilling.value,
				},
				{
					label: 'Reports',
					icon: 'lucide-chart-no-axes-column',
					to: '/billing/reports',
					condition: canViewBilling.value,
				},
				{
					label: 'Limit tiers',
					icon: 'lucide-layers',
					to: '/billing/limits',
					condition: canViewBilling.value,
				},
			],
		},
	]
})
