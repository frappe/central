import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { reportError, successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'

// The team's AI, served by Grove. Grove owns the keys: Central lists them masked, and a
// key's secret is shown once, in the answer that mints it. One module-level composable
// so the page and its tabs share one fetch; the server re-checks every capability.

export type AIDialect = 'openai' | 'anthropic'

export interface AIModel {
	name: string
	// What the model takes and what it gives: text, image, embeddings, ...
	input_modalities: string[]
	output_modalities: string[]
	// The API surfaces this model answers on.
	dialects: AIDialect[]
}

// Per-minute limits counted across every key of the team. null means no limit.
export interface AIRateLimits {
	requests_per_minute: number | null
	tokens_per_minute: number | null
}

export interface AIState {
	enabled: boolean
	models?: AIModel[]
	rate_limits?: AIRateLimits
}

export interface AIUsageModel {
	model: string
	requests: number
	cost: number
}

// One day of one model. Every day of the period is present, zeros included.
export interface AIUsageDay {
	day: string
	model: string
	requests: number
	cost: number
}

// What the team used over a period: requests and cost (USD), in total, per model and
// per day. Grove does the sums.
export interface AIUsage {
	period: string
	from_date: string
	to_date: string
	as_of: string | null
	totals: { requests: number; cost: number }
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

const { activeTeam } = useSession()

const aiCall = useCall<AIState, { team: string }>({
	url: method(API.ai),
	params: teamParams,
	immediate: false,
	refetch: true,
})

whenTeamReady(() => aiCall.reload())

const usageParams = ref<{ team: string; period: string; key?: string }>({
	team: '',
	period: '',
})
const usageCall = useCall<AIUsage, typeof usageParams.value>({
	url: method(API.aiUsage),
	params: () => usageParams.value,
	immediate: false,
})

const enableCall = useCall<{ name: string }, { team: string }>({
	url: method(API.enableAI),
	method: 'POST',
	immediate: false,
})

const apiKeysCall = useCall<AIApiKey[], { team: string }>({
	url: method(API.aiApiKeys),
	params: teamParams,
	immediate: false,
})

const createKeyCall = useCall<MintedKey, { team: string; label: string }>({
	url: method(API.createAIApiKey),
	method: 'POST',
	immediate: false,
})

const revokeKeyCall = useCall<{ name: string }, { team: string; key: string }>({
	url: method(API.revokeAIApiKey),
	method: 'POST',
	immediate: false,
})

// Row-level busy: the key currently mutating, so its control alone spins.
const busyKey = ref('')

export function useAI() {
	return {
		ai: computed<AIState | null>(() => aiCall.data ?? null),
		aiLoading: computed(() => aiCall.loading),
		models: computed(() => aiCall.data?.models ?? []),

		// Errors bubble so the caller decides how to show them.
		async enable(): Promise<void> {
			await submitOrThrow(enableCall, { team: activeTeam.value! })
			await aiCall.reload()
		},

		usage: computed<AIUsage | null>(() => usageCall.data ?? null),
		usageLoading: computed(() => usageCall.loading),
		usageError: computed(() => usageCall.error),
		loadUsage(filters: UsageFilters): Promise<unknown> {
			usageParams.value = {
				team: activeTeam.value!,
				period: filters.period,
				...(filters.key ? { key: filters.key } : {}),
			}
			return usageCall.reload()
		},

		apiKeys: computed(() => apiKeysCall.data ?? []),
		apiKeysLoading: computed(() => apiKeysCall.loading),
		busyKey: computed(() => busyKey.value),
		loadApiKeys: (): Promise<unknown> => apiKeysCall.reload(),

		// Throws so the caller can show the secret, or an inline error, itself.
		async createApiKey(label: string): Promise<MintedKey> {
			await submitOrThrow(createKeyCall, { team: activeTeam.value!, label })
			await apiKeysCall.reload()
			return createKeyCall.data!
		},

		async revokeApiKey(key: string): Promise<void> {
			busyKey.value = key
			try {
				await submitOrThrow(revokeKeyCall, { team: activeTeam.value!, key })
				successToast(
					'API key revoked. It can take a few minutes to stop working.',
				)
				await apiKeysCall.reload()
			} catch (e) {
				reportError(e)
			} finally {
				busyKey.value = ''
			}
		},
	}
}
