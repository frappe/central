import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type {
	AIApiKey,
	AIState,
	AIUsage,
	MintedKey,
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

const balanceAccessCall = useCall<
	{ name: string; can_read_balance: boolean },
	{ team: string; key: string; can_read_balance: boolean }
>({
	url: method(API.setAIApiKeyBalanceAccess),
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
		models: computed(() => aiCall.data?.models ?? []),

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

		async createApiKey(label: string): Promise<MintedKey> {
			await submitOrThrow(createKeyCall, { team: activeTeam.value!, label })
			await apiKeysCall.reload()
			return createKeyCall.data!
		},

		async setBalanceAccess(key: string, allowed: boolean): Promise<void> {
			busyKey.value = key
			try {
				await submitOrThrow(balanceAccessCall, {
					team: activeTeam.value!,
					key,
					can_read_balance: allowed,
				})
				await apiKeysCall.reload()
			} finally {
				busyKey.value = ''
			}
		},

		async revokeApiKey(key: string): Promise<void> {
			busyKey.value = key
			try {
				await submitOrThrow(revokeKeyCall, { team: activeTeam.value!, key })
				successToast(
					'API key revoked. It can take a few minutes to stop working.',
				)
				await apiKeysCall.reload()
			} finally {
				busyKey.value = ''
			}
		},
	}
}
