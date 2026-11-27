import { compactNumber } from '@/lib/format'
import type { AIRateLimit } from '@/types/ai'

const METRIC_LETTERS: Record<string, string> = {
	requests: 'R',
	total_tokens: 'T',
}
const WINDOW_LETTERS: Record<string, string> = {
	'1m': 'PM',
	'1h': 'PH',
	'1d': 'PD',
	'1M': 'PMo',
}
const METRIC_WORDS: Record<string, string> = {
	requests: 'requests',
	total_tokens: 'tokens',
}
const WINDOW_WORDS: Record<string, string> = {
	'1m': 'per minute',
	'1h': 'per hour',
	'1d': 'per day',
	'1M': 'per month',
}

export interface LimitChip {
	key: string
	label: string
	text: string
}

// The rows that hold on `model` in `geography`: the ones naming it and, on every metric and
// window none of those covers, the ones naming no model.
export const limitsFor = (
	limits: AIRateLimit[],
	model: string,
	geography: string,
): AIRateLimit[] => {
	const slot = (limit: AIRateLimit) => `${limit.metric}:${limit.window}`
	const reaching = limits.filter(
		(limit) => !limit.geography || limit.geography === geography,
	)
	const named = reaching.filter((limit) => limit.model_key === model)
	const covered = new Set(named.map(slot))
	return [
		...named,
		...reaching.filter(
			(limit) => !limit.model_key && !covered.has(slot(limit)),
		),
	]
}

// One chip per limit, `20 RPM`; the long form goes in its tooltip and ends with `counted`
// (`per key`). A row at 0 is no limit: `∞ RPM`.
export const limitChips = (
	limits: AIRateLimit[],
	counted: string,
): LimitChip[] =>
	limits.map((limit) => ({
		key: `${limit.model_key}:${limit.metric}:${limit.window}`,
		label: `${limit.value ? compactNumber(limit.value) : '∞'} ${METRIC_LETTERS[limit.metric] ?? limit.metric}${WINDOW_LETTERS[limit.window] ?? ''}`,
		text: `${limit.value ? limit.value.toLocaleString() : 'No limit on'} ${METRIC_WORDS[limit.metric] ?? limit.metric} ${WINDOW_WORDS[limit.window] ?? limit.window} ${counted}`,
	}))
