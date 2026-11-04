import type { DropdownOption } from 'frappe-ui'
import { ref } from 'vue'

/** The server a ticket was opened from, so the dialog fills it in at once. */
export interface SupportServer {
	name?: string | null
	resource_id: string
	title?: string | null
	region?: string | null
	plan?: string | null
	status?: string | null
}

/** What the ticket is about, such as `{ Server: 'acme (vm-1)', Site: 'acme.test' }`.
 *  Empty values are left out of the subject. */
export type SupportContext = Record<
	string,
	string | null | undefined | SupportServer
>

export type SupportCategoryKey = 'server' | 'site' | 'billing' | 'account'

export interface SupportCategory {
	label: string
	/** One line under the card in the dialog. */
	description: string
	icon: string
	/** Mirrors central.api.support.SUPPORT_CATEGORIES, which validates every ticket. */
	issues: readonly string[]
}

export const SUPPORT_CATEGORIES: Record<SupportCategoryKey, SupportCategory> = {
	server: {
		label: 'Server',
		description: 'Power, disk, network, or console trouble.',
		icon: 'lucide-server',
		issues: [
			'Unreachable or down',
			'Slow performance or high load',
			'Resize, disk, or plan',
			'SSH, console, or networking',
			'Snapshots or backups',
			'Other server issue',
		],
	},
	site: {
		label: 'Site & app',
		description: 'Setup, domains, apps, or email delivery.',
		icon: 'lucide-globe',
		issues: [
			'Site setup or provisioning failed',
			'Domain, DNS, or SSL certificate',
			'App installation or update',
			'Sign-in or administrator access',
			'Email delivery',
			'Other site issue',
		],
	},
	billing: {
		label: 'Billing & plans',
		description: 'Invoices, payments, credits, or plans.',
		icon: 'lucide-credit-card',
		issues: [
			'Invoice or tax question',
			'Payment method or failed charge',
			'Credits or spending limit',
			'Plan or subscription',
			'Other billing question',
		],
	},
	account: {
		label: 'Account & team',
		description: 'Sign-in, members, roles, or managed services.',
		icon: 'lucide-users',
		issues: [
			'Sign-in or verification',
			'Team members, roles, or invitations',
			'Object storage or LLM service',
			'Team suspension or archive',
			'Other account question',
		],
	},
}

/** The dialog sits above the page, so its state is shared: any surface that offers
 *  support opens the same one. */
export const supportDialogOpen = ref(false)
export const supportDialogTab = ref<'new' | 'open'>('new')
export const supportDialogContext = ref<SupportContext>({})

export function openSupportDialog(
	context: SupportContext = {},
	tab: 'new' | 'open' = 'new',
): void {
	supportDialogContext.value = context
	supportDialogTab.value = tab
	supportDialogOpen.value = true
}

/** The server a surface passed along, so a dialog opened from its page can name it at once. */
export function getSupportServer(
	context: SupportContext,
): SupportServer | null {
	const server = context.server
	return server && typeof server === 'object' ? server : null
}

/** Picks the category card that fits the place the user asked for help. */
export function getSupportCategory(
	context: SupportContext,
): SupportCategoryKey | null {
	if (context.Server || getSupportServer(context)) return 'server'
	if (context.Site) return 'site'

	const words = [context.Category, context.Topic]
		.filter((value): value is string => typeof value === 'string')
		.join(' ')
	if (/\b(billing|invoice|payment|credit|spending limit|plan)\b/i.test(words))
		return 'billing'
	if (/\b(account|sign-in|member|invitation|role|storage|llm)\b/i.test(words))
		return 'account'

	return null
}

/** Contact support and feedback links from Central Settings. An unset URL hides its
 *  entry. With API credentials, the console opens its own ticket dialog instead. */
export function useSupport() {
	const {
		support_ticket_url: ticketUrl,
		feedback_url: feedbackUrl,
		in_app_tickets: inAppTickets,
	} = window.help_links ?? {}

	// Guest pages carry no team, so they keep the external URL.
	const isSignedIn = Boolean(window.user) && window.user !== 'Guest'
	const canUseInAppTickets = Boolean(inAppTickets && isSignedIn)
	const hasSupport = Boolean(canUseInAppTickets || ticketUrl)

	const getTicketUrl = (context: SupportContext = {}): string | null => {
		if (!ticketUrl) return null

		const url = new URL(ticketUrl)
		const subject = getTicketSubject(context)
		if (subject) url.searchParams.set('q', subject)
		url.searchParams.set('utm_source', 'central')
		return url.toString()
	}

	const openSupport = (
		context: SupportContext = {},
		tab: 'new' | 'open' = 'new',
	): void => {
		if (canUseInAppTickets) {
			openSupportDialog(context, tab)
			return
		}

		const url = getTicketUrl(context)
		if (url) openInNewTab(url)
	}

	const getContactSupportOption = (
		context: SupportContext = {},
	): DropdownOption | null => {
		if (!hasSupport) return null

		return {
			label: 'Contact support',
			icon: 'lucide-life-buoy',
			onClick: () => openSupport(context, 'new'),
		}
	}

	const feedbackOption: DropdownOption | null = feedbackUrl
		? {
				label: 'Share feedback',
				icon: 'lucide-message-square-text',
				onClick: () => openInNewTab(feedbackUrl),
			}
		: null

	return {
		getTicketUrl,
		getContactSupportOption,
		feedbackOption,
		hasSupport,
		canUseInAppTickets,
		openSupport,
	}
}

/** `[Server: acme (vm-1) · Site: acme.test] `, ending in a space so the customer types on.
 *  A structured value, such as the server itself, is context for the dialog, not the subject. */
export function getTicketSubject(context: SupportContext): string {
	const parts = Object.entries(context)
		.filter(([, value]) => typeof value === 'string' && value)
		.map(([label, value]) => `${label}: ${value}`)
	return parts.length ? `[${parts.join(' · ')}] ` : ''
}

function openInNewTab(url: string): void {
	window.open(url, '_blank', 'noopener')
}
