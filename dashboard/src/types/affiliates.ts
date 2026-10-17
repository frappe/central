export type AffiliateStatus = 'Pending' | 'Active' | 'Rejected' | 'Disabled'

/** The signed-in user's own affiliate account (get_affiliate, apply). */
export interface AffiliateState {
	status: AffiliateStatus
	affiliate_code: string | null
	rejection_reason: string | null
}

/** How many reached each step. A later step implies the earlier ones. */
export interface FunnelCounts {
	visited: number
	signed_up: number
	created_site: number
	added_billing: number
	converted: number
}

/** One row of a breakdown table: a link, source, product or country, and its funnel. */
export interface FunnelRow extends FunnelCounts {
	label: string
}

export interface DailyCounts {
	day: string
	clicks: number
	signups: number
	paying: number
}

/** The affiliate's funnel for a date range (get_summary). It never names a team. */
export interface AffiliateSummary {
	totals: FunnelCounts
	/** The same numbers for the period of the same length just before. */
	previous_totals: FunnelCounts
	daily: DailyCounts[]
	by_link: (FunnelCounts & { link: string })[]
	by_source: (FunnelCounts & { source: string })[]
	by_product: (FunnelCounts & { product: string })[]
	by_country: (FunnelCounts & { country: string })[]
}

/** A named link such as /r/bwh (get_links). */
export interface AffiliateLink {
	slug: string
	product: string | null
	utm_source: string | null
	utm_campaign: string | null
	creation: string
}

export interface NewAffiliateLink {
	slug: string
	product: string
	utm_source: string
	utm_campaign: string
}

/** Of the customers who started paying that many months ago, how many still pay. */
export interface RetentionPoint {
	/** Months since the first payment, from 1. */
	month: number
	customers: number
	still_paying: number
	percent: number
}

/** How long the affiliate's paying customers keep paying (get_retention). */
export interface AffiliateRetention {
	customers: number
	/** Customers who paid an invoice in the last 30 days. */
	active_30_days: number
	/** Customers who paid an invoice in the last 90 days. */
	active_90_days: number
	/** Customers who paid in each of the last 12 months, oldest first. */
	trend: number[]
	curve: RetentionPoint[]
}

export interface LinkProduct {
	name: string
	title: string
}
