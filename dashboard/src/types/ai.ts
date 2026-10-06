// What central.services.api.ai answers with. Grove owns the keys: Central lists them
// masked, and a key's secret is shown once, in the answer that mints it.

export type AIDialect = 'openai' | 'anthropic'

export interface AIModel {
	name: string
	// What the model takes and what it gives: text, image, embeddings, ...
	input_modalities: string[]
	output_modalities: string[]
	// The API surfaces this model answers on.
	dialects: AIDialect[]
}

// One limit Grove counts across every key of the team: a metric over a window.
export interface AIRateLimit {
	metric: 'requests' | 'total_tokens' | string
	window: '1m' | '1h' | '1d' | '1M' | string
	value: number
}

// USD, as of Grove's last pull. A free team is never charged: `spent` stays at zero.
export interface AIBalance {
	balance: number
	spent: number
	is_free_user: boolean
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
	// Where the team's keys call: the base for both API surfaces.
	gateway_url?: string | null
	models?: AIModel[]
	rate_limits?: AIRateLimit[]
	balance?: AIBalance
	usage?: AIMonthUsage
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

// A key as listed: never its secret.
export interface AIApiKey {
	name: string
	title: string
	status: 'active' | 'revoked'
	creation: string
	// UTC; Grove refuses to revoke a key before this, so the console does not ask.
	revocable_at: string
	masked: string
	can_read_balance: number
}

// A key just minted: the only answer that carries its secret.
export interface MintedKey {
	name: string
	label: string
	gateway_url: string
	api_key: string
}
