import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type {
	AIApiKey,
	AIModel,
	AIState,
	AIUsage,
	MintedKey,
	NewKey,
	UsageFilters,
} from '@/types/ai'

// The team's AI, served by Grove. One module-level composable so the page and its
// tabs share one fetch; the server re-checks every capability. Mutations throw, so
// the caller shows the result (a minted secret, an inline error) itself.

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

const createKeyCall = useCall<
	MintedKey,
	{ team: string; label: string; geography: string; cap?: number }
>({
	url: method(API.createAIApiKey),
	method: 'POST',
	immediate: false,
})

const updateKeyCall = useCall<
	AIApiKey,
	{ team: string; key: string; cap: number }
>({
	url: method(API.updateAIApiKey),
	method: 'POST',
	immediate: false,
})

const keyModelsParams = ref<{ team: string; key: string }>({
	team: '',
	key: '',
})
const keyModelsCall = useCall<AIModel[], typeof keyModelsParams.value>({
	url: method(API.aiApiKeyModels),
	params: () => keyModelsParams.value,
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
		aiError: computed(() => aiCall.error),
		reloadAI: (): Promise<unknown> => aiCall.reload(),

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
		apiKeysError: computed(() => apiKeysCall.error),
		busyKey: computed(() => busyKey.value),
		loadApiKeys: (): Promise<unknown> => apiKeysCall.reload(),

		async createApiKey(key: NewKey): Promise<MintedKey> {
			await submitOrThrow(createKeyCall, { team: activeTeam.value!, ...key })
			// A cap moves what is unallocated, so the overview reloads with the list.
			await Promise.all([apiKeysCall.reload(), aiCall.reload()])
			return createKeyCall.data!
		},

		async setCap(key: string, cap: number): Promise<void> {
			busyKey.value = key
			try {
				await submitOrThrow(updateKeyCall, {
					team: activeTeam.value!,
					key,
					cap,
				})
				await Promise.all([apiKeysCall.reload(), aiCall.reload()])
			} finally {
				busyKey.value = ''
			}
		},

		// What one key may call, as its geography serves them: fetched when asked for.
		keyModels: computed<AIModel[]>(() => keyModelsCall.data ?? []),
		keyModelsLoading: computed(() => keyModelsCall.loading),
		loadKeyModels(key: string): Promise<unknown> {
			keyModelsParams.value = { team: activeTeam.value!, key }
			return keyModelsCall.reload()
		},

		async revokeApiKey(key: string): Promise<void> {
			busyKey.value = key
			try {
				await submitOrThrow(revokeKeyCall, { team: activeTeam.value!, key })
				successToast(
					'API key revoked. It can take a few minutes to stop working.',
				)
				await Promise.all([apiKeysCall.reload(), aiCall.reload()])
			} finally {
				busyKey.value = ''
			}
		},
	}
}
