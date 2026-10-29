import type { SidebarSection } from '../node_modules/frappe-ui/vitepress/index.node'

export const sidebar: SidebarSection[] = [
	{
		text: 'Get started',
		items: [
			{ text: 'Overview', link: '/' },
			{ text: 'Quick start', link: '/get-started/quick-start' },
			{ text: 'How Frappe Cloud works', link: '/get-started/how-it-works' },
			{ text: 'Tour the console', link: '/get-started/console' },
		],
	},
	{
		text: 'Servers',
		items: [
			{ text: 'Servers', link: '/servers/' },
			{ text: 'Create a server', link: '/servers/create' },
			{ text: 'Images', link: '/servers/images' },
			{ text: 'Regions', link: '/servers/regions' },
			{ text: 'Monitor usage', link: '/servers/usage' },
			{ text: 'Connect with SSH', link: '/servers/access' },
			{ text: 'Networking and firewall', link: '/servers/networking' },
			{ text: 'WireGuard VPN', link: '/servers/wireguard' },
			{ text: 'Snapshots', link: '/servers/snapshots' },
			{ text: 'Resize, stop, and terminate', link: '/servers/lifecycle' },
		],
	},
	{
		text: 'Pilot',
		items: [
			{ text: 'What Pilot is', link: '/pilot/' },
			{ text: 'Benches', link: '/pilot/benches' },
			{ text: 'Sites', link: '/pilot/sites' },
			{ text: 'Apps', link: '/pilot/apps' },
			{ text: 'Domains and SSL', link: '/pilot/domains' },
			{ text: 'Backups and restore', link: '/pilot/backups' },
			{ text: 'Database access', link: '/pilot/database' },
			{ text: 'Updates and migrations', link: '/pilot/updates' },
			{ text: 'Logs and tasks', link: '/pilot/logs' },
			{ text: 'SSH keys and code editor', link: '/pilot/tools' },
		],
	},
	{
		text: 'Team and access',
		items: [
			{ text: 'Members and invitations', link: '/team/members' },
			{ text: 'Roles and permissions', link: '/team/roles' },
			{ text: 'Team settings', link: '/team/settings' },
		],
	},
	{
		text: 'Billing',
		items: [
			{ text: 'How billing works', link: '/billing/' },
			{ text: 'Payment methods', link: '/billing/payment-methods' },
			{ text: 'Invoices', link: '/billing/invoices' },
			{ text: 'Credits and spend limits', link: '/billing/limits' },
		],
	},
	{
		text: 'Account',
		items: [
			{ text: 'Profile and theme', link: '/account/profile' },
			{ text: 'Notifications', link: '/account/notifications' },
		],
	},
	{
		text: 'Help',
		items: [{ text: 'Troubleshooting', link: '/help/troubleshooting' }],
	},
]
