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

// One chip per limit: `10 RPM gpt-6-luna`, the model's id when the row names one; the long form
// goes in its tooltip. A row at 0 is no limit there: `∞ RPM gpt-6-luna`.
export const limitChips = (
	limits: AIRateLimit[],
	scope: 'Model' | 'Key' = 'Model',
): LimitChip[] =>
	limits.map((limit) => {
		const model = limit.model_key ? ` ${limit.model_key.split('/').pop()}` : ''
		const where =
			scope === 'Key' ? 'per key' : `on ${limit.model_key || 'every model'}`
		return {
			key: `${limit.model_key}:${limit.metric}:${limit.window}`,
			label: `${limit.value ? compactNumber(limit.value) : '∞'} ${METRIC_LETTERS[limit.metric] ?? limit.metric}${WINDOW_LETTERS[limit.window] ?? ''}${model}`,
			text: `${limit.value ? limit.value.toLocaleString() : 'No limit on'} ${METRIC_WORDS[limit.metric] ?? limit.metric} ${WINDOW_WORDS[limit.window] ?? limit.window} ${where}`,
		}
	})
