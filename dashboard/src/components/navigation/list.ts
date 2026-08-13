import { type Component, computed, defineAsyncComponent } from 'vue'
import { useCapabilities } from '@/composables/useCapabilities'
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
	const { canViewServers, canViewBilling, canViewServices, isMember } =
		useCapabilities()

	return [
		{
			label: '',
			items: [
				{ label: 'Search', icon: 'lucide-search', onClick: openSearch },
				{
					label: 'Notifications',
					icon: 'lucide-bell',
					condition: isMember.value,
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
					label: 'Addons',
					icon: 'lucide-blocks',
					to: '/addons',
					condition: features.addons && canViewServices.value,
				},
				{
					label: 'Teams',
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
					label: 'Limit Tiers',
					icon: 'lucide-layers',
					to: '/billing/limits',
					condition: canViewBilling.value,
				},
			],
		},
	]
})
