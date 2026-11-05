import type { DropdownOption } from 'frappe-ui'

/** What the ticket is about, such as `{ Server: 'acme (vm-1)', Site: 'acme.test' }`.
 *  Empty values are left out of the subject. */
export type SupportContext = Record<string, string | null | undefined>

/** Contact support and feedback links from Central Settings. The helpdesk customer portal
 *  prefills only the subject, from its `q` parameter, so the context goes there. An unset
 *  URL hides its entry. */
export function useSupport() {
	const { support_ticket_url: ticketUrl, feedback_url: feedbackUrl } =
		window.help_links ?? {}

	const getTicketUrl = (context: SupportContext = {}): string | null => {
		if (!ticketUrl) return null

		const url = new URL(ticketUrl)
		const subject = getTicketSubject(context)
		if (subject) url.searchParams.set('q', subject)
		url.searchParams.set('utm_source', 'central')
		return url.toString()
	}

	const getContactSupportOption = (
		context: SupportContext = {},
	): DropdownOption | null => {
		const url = getTicketUrl(context)
		if (!url) return null

		return {
			label: 'Contact support',
			icon: 'lucide-life-buoy',
			onClick: () => openInNewTab(url),
		}
	}

	const feedbackOption: DropdownOption | null = feedbackUrl
		? {
				label: 'Share feedback',
				icon: 'lucide-message-square-text',
				onClick: () => openInNewTab(feedbackUrl),
			}
		: null

	return { getTicketUrl, getContactSupportOption, feedbackOption }
}

/** `[Server: acme (vm-1) · Site: acme.test] `, ending in a space so the customer types on. */
export function getTicketSubject(context: SupportContext): string {
	const parts = Object.entries(context)
		.filter(([, value]) => value)
		.map(([label, value]) => `${label}: ${value}`)
	return parts.length ? `[${parts.join(' · ')}] ` : ''
}

function openInNewTab(url: string): void {
	window.open(url, '_blank', 'noopener')
}
