// What central.services.api.ai answers with. Grove owns the keys and each key's policy:
// Central lists them masked, and a key's secret is shown once, in the answer that mints it.

export type AIDialect = 'openai' | 'anthropic'

export interface AIModel {
	name: string
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

// USD, as of Grove's last pull. `unallocated` is what no key's cap has claimed yet. A free
// team is never charged: `spent` stays at zero and caps do not apply.
export interface AIBalance {
	balance: number
	spent: number
	unallocated: number
	is_free_user: boolean
}

// Where a key may be minted, and the gateway its keys call.
export interface AIGeography {
	name: string
	label: string
	endpoint: string
	is_default: boolean
}

// This month so far, with the window and when Grove last counted.
export interface AIMonthUsage {
	requests: number
	tokens: number
	cost: number
	from_date: string
	to_date: string
	as_of: string | null
}

export interface AIState {
	enabled: boolean
	balance?: AIBalance
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

// A key as listed: never its secret. Its geography never changes; its cap may.
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
	// USD: what the key may spend out of the team's balance, and what it has.
	cap: number
	spent: number
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
