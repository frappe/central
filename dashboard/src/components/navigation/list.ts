import { computed } from 'vue'
import { useCapabilities } from '@/composables/useCapabilities'

export const sidebarSections = computed(() => {
	const { canViewServers, canViewBilling, canViewServices, isMember } =
		useCapabilities()

	return [
		{
			items: [
				{ label: 'Search', icon: 'lucide-search' },
				{
					label: 'Notifications',
					icon: 'lucide-bell',
					to: '/notifications',
					condition: isMember.value,
					class: 'mb-3',
				},
			],
		},

		{
			items: [
				{
					label: 'Servers',
					icon: 'lucide-server',
					to: '/servers',
					condition: canViewServers.value,
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
			label: 'Services',
			collapsible: true,
			items: [
				{
					label: 'LLM',
					icon: 'lucide-sparkles',
					to: '/services/llm',
					condition: canViewServices.value,
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
