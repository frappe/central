import type { DropdownOption } from 'frappe-ui'
import { ref } from 'vue'
import { __ } from '@/lib/translate'

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

/** What the dialog shows for a category. The catalog, and its issues, come from Central. */
export interface SupportCategoryDetails {
	description: string
	icon: string
}

export const SUPPORT_CATEGORY_DETAILS: Record<
	SupportCategoryKey,
	SupportCategoryDetails
> = {
	server: {
		description: __('Power, disk, network, or console trouble.'),
		icon: 'lucide-server',
	},
	site: {
		description: __('Setup, domains, apps, or email delivery.'),
		icon: 'lucide-globe',
	},
	billing: {
		description: __('Invoices, payments, credits, or plans.'),
		icon: 'lucide-credit-card',
	},
	account: {
		description: __('Sign-in, members, roles, or managed services.'),
		icon: 'lucide-users',
	},
}

export interface SupportIssueOption {
	label: string
	is_critical: boolean
}

export interface SupportCategoryOption {
	key: SupportCategoryKey
	label: string
	issues: SupportIssueOption[]
}

export interface SupportArticle {
	name: string
	title: string
	excerpt: string
	category: string | null
	url: string
}

export interface SupportRelatedTicket {
	name: string
	subject: string
	status: string | null
	/** The email that raised the ticket. */
	raised_by?: string | null
	/** Null for a teammate's ticket, which the support portal does not open for this user. */
	url: string | null
}

export interface SupportRelatedResults {
	articles: SupportArticle[]
	tickets: SupportRelatedTicket[]
}

export interface SupportTicket {
	name: string
	subject: string
	status: string
	creation?: string | null
	/** The email that raised the ticket. */
	raised_by?: string | null
	/** Null for a teammate's ticket, which the support portal does not open for this user. */
	url?: string | null
}

/** `Production Web (vm-1)`, or the id alone when the server has no title. */
export function getServerReference(server: SupportServer): string {
	return server.title
		? `${server.title} (${server.resource_id})`
		: server.resource_id
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
		articles_enabled: isAnswersFirst,
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
			label: __('Contact support'),
			icon: 'lucide-life-buoy',
			onClick: () => openSupport(context, 'new'),
		}
	}

	const feedbackOption: DropdownOption | null = feedbackUrl
		? {
				label: __('Share feedback'),
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
		isAnswersFirst: Boolean(isAnswersFirst),
		openSupport,
	}
}

/** `[Server: acme (vm-1) · Site: acme.test] `, ending in a space so the customer types on.
 *  A structured server is named from its title and resource id, so callers pass it once. */
export function getTicketSubject(context: SupportContext): string {
	const server = getSupportServer(context)
	const parts = Object.entries(context)
		.filter(
			([label, value]) =>
				label !== 'server' &&
				!(server && label === 'Server') &&
				typeof value === 'string' &&
				value,
		)
		.map(([label, value]) => `${label}: ${value}`)
	if (server) parts.unshift(`Server: ${getServerReference(server)}`)

	return parts.length ? `[${parts.join(' · ')}] ` : ''
}

function openInNewTab(url: string): void {
	window.open(url, '_blank', 'noopener')
}
