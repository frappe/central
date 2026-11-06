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

export const METRIC_OPTIONS = [
	{ label: 'Requests', value: 'requests' },
	{ label: 'Tokens', value: 'total_tokens' },
]
export const WINDOW_OPTIONS = [
	{ label: 'Per minute', value: '1m' },
	{ label: 'Per hour', value: '1h' },
	{ label: 'Per day', value: '1d' },
	{ label: 'Per month', value: '1M' },
]

export interface LimitChip {
	key: string
	label: string
	text: string
}

// One chip per limit: `10 RPM gpt-6-luna`, the model's id when the row names one; the long form
// goes in its tooltip.
export const limitChips = (limits: AIRateLimit[]): LimitChip[] =>
	limits.map((limit) => {
		const model = limit.model_key ? ` ${limit.model_key.split('/').pop()}` : ''
		return {
			key: `${limit.model_key}:${limit.metric}:${limit.window}`,
			label: `${compactNumber(limit.value)} ${METRIC_LETTERS[limit.metric] ?? limit.metric}${WINDOW_LETTERS[limit.window] ?? ''}${model}`,
			text: `${limit.value.toLocaleString()} ${METRIC_WORDS[limit.metric] ?? limit.metric} ${WINDOW_WORDS[limit.window] ?? limit.window} on ${limit.model_key || 'every model'}`,
		}
	})
