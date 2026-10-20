// What central.services.api.ai answers with. Grove owns the keys and each key's policy:
// Central lists them masked, and a key's secret is shown once, in the answer that mints it.

export type AIDialect = 'openai' | 'anthropic'

export interface AIModel {
	// The key a caller sends: `provider/model_id`.
	name: string
	provider: string
	model_id: string
	// What the model takes and what it gives: text, image, embeddings, ...
	input_modalities: string[]
	output_modalities: string[]
	// The API surfaces this model answers on.
	dialects: AIDialect[]
}

// One limit Grove counts for one key: a metric over a window.
export interface AIRateLimit {
	metric: 'requests' | 'total_tokens' | string
	window: '1m' | '1h' | '1d' | '1M' | string
	value: number
}

// USD, as of Grove's last pull. `capped` is Σ the live keys' monthly caps; `committed` is what
// this month has spoken for of the tier's `spend_limit`: each live key's cap or its month's spend,
// whichever is more, plus what revoked keys spent. Grove checks a raise against `committed`.
// Credit and invoices are Central's wallet and invoicing, not Grove's.
export interface AISpend {
	month_spent: number
	capped: number
	committed: number
	spend_limit: number
	// How many live keys the plan allows; 0 is no limit.
	max_keys: number
	suspended: boolean
	// Whether the gateways keep the team's prompts and outputs for a short time, for support.
	log_payloads: boolean
}

// Where a key may be minted, and the gateway its keys call.
export interface AIGeography {
	name: string
	label: string
	// null while the geography has no gateway yet: a key cannot be minted there
	endpoint: string | null
	is_default: boolean
}

// This month so far, with the window, when Grove last counted, and one total per day
// so far for the overview's sparklines.
export interface AIMonthUsage {
	requests: number
	tokens: number
	cost: number
	from_date: string
	to_date: string
	as_of: string | null
	daily: Omit<AIUsageDay, 'model'>[]
}

export interface AIState {
	enabled: boolean
	// Grove is down or in maintenance: nothing else is filled in.
	unavailable?: boolean
	spend?: AISpend
	usage?: AIMonthUsage
	geographies?: AIGeography[]
}

export interface AIUsageModel {
	model: string
	requests: number
	tokens: number
	cost: number
}

// One day of one model. Every day of the period is present, zeros included.
export interface AIUsageDay {
	day: string
	model: string
	requests: number
	tokens: number
	cost: number
}

// What the team used over a period: requests and cost (USD), in total, per model and
// per day. Grove does the sums.
export interface AIUsage {
	period: string
	from_date: string
	to_date: string
	as_of: string | null
	totals: { requests: number; tokens: number; cost: number }
	models: AIUsageModel[]
	daily: AIUsageDay[]
}

// A named period, and one API key by name, or every key when absent.
export interface UsageFilters {
	period: string
	key?: string
}

// A key as listed: never its secret. Its geography never changes; its cap, whole USD, may.
export interface AIApiKey {
	name: string
	title: string
	status: 'active' | 'revoked'
	creation: string
	// UTC; Grove refuses to revoke a key before this, so the console does not ask.
	revocable_at: string
	masked: string
	geography: string
	// The base URL for both API surfaces, of the key's own geography.
	gateway_url: string
	// USD: what the key may spend a month and what it spent this month.
	cap: number
	month_spent: number
	limits: AIRateLimit[]
}

// What a new key is minted with.
export interface NewKey {
	label: string
	geography: string
	cap?: number
}

// A key just minted: the only answer that carries its secret, with what it may call.
export interface MintedKey {
	name: string
	label: string
	geography: string
	gateway_url: string
	api_key: string
	models: AIModel[]
}
