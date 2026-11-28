export type AffiliateStatus = 'Active' | 'Paused'

export interface Affiliate {
	code: string
	status: AffiliateStatus
	link: string
	/** 0 when an operator disabled the affiliate: it stays paused and cannot turn on again. */
	enabled: 0 | 1
}

export interface AffiliateProduct {
	name: string
	title: string
}

/** Where an affiliate posts a link. `name` goes in the link as `utm_source`. */
export interface AffiliateSource {
	name: string
	title: string
	/** 0 hides it from Make a link. Its title still names old signups. */
	enabled: 0 | 1
}

export interface AffiliateProgram {
	affiliate: Affiliate | null
	/** Days a click on the link counts toward a signup. */
	cookie_days: number
	/** Enabled products a link can send people to. */
	products: AffiliateProduct[]
	sources: AffiliateSource[]
}

export type AffiliatePeriod = '30d' | '90d' | '12m' | 'all'

export interface AffiliateCounts {
	signups: number
	paying: number
}

export interface AffiliateTotals extends AffiliateCounts {
	still_paying: number
	still_paying_days: number
	/** Null for all time, which has no period before it. */
	previous_signups: number | null
	previous_paying: number | null
}

export interface AffiliateFunnel {
	signed_up: number
	started_site: number
	added_card: number
	paying: number
	waiting_to_pay: number
}

export interface AffiliateCampaign extends AffiliateCounts {
	campaign: string | null
	source: string | null
	product: string
	post_url: string | null
}

export interface AffiliatePerformance {
	totals: AffiliateTotals
	funnel: AffiliateFunnel
	weekly: (AffiliateCounts & { week: string })[]
	by_source: (AffiliateCounts & { source: string | null })[]
	by_product: (AffiliateCounts & { product: string })[]
	campaigns: AffiliateCampaign[]
}
