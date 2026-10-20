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

// The secret of the key just minted, shown once. Kept here, not in the keys tab, so the page
// shows it from outside the tab area: a reload that comes back unavailable cannot unmount it.
const minted = ref<MintedKey | null>(null)

const capsCall = useCall<
	AIApiKey[],
	{ team: string; caps: Record<string, number> }
>({
	url: method(API.setAIApiKeyCaps),
	method: 'POST',
	immediate: false,
})

const modelsParams = ref<{ team: string; geography: string }>({
	team: '',
	geography: '',
})
const modelsCall = useCall<AIModel[], typeof modelsParams.value>({
	url: method(API.aiModels),
	params: () => modelsParams.value,
	immediate: false,
})

const revokeKeyCall = useCall<{ name: string }, { team: string; key: string }>({
	url: method(API.revokeAIApiKey),
	method: 'POST',
	immediate: false,
})

const pullCall = useCall<{ sync: string | null }, { team: string }>({
	url: method(API.pullAIUsage),
	method: 'POST',
	immediate: false,
})

const promptLoggingCall = useCall<
	{ log_payloads: boolean },
	{ team: string; enabled: boolean }
>({
	url: method(API.setAIPromptLogging),
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

		minted: computed(() => minted.value),
		dismissMinted(): void {
			minted.value = null
		},

		async createApiKey(key: NewKey): Promise<void> {
			await submitOrThrow(createKeyCall, { team: activeTeam.value!, ...key })
			// The secret is on screen before anything else can fail. A cap moves the room left
			// under the spend limit, so the list and the overview reload after it; a reload that
			// fails lands in its own error state and takes nothing from the dialog.
			minted.value = createKeyCall.data!
			void Promise.all([apiKeysCall.reload(), aiCall.reload()]).catch(() => {})
		},

		// Every cap in one call: Grove saves all or none, so caps can move between keys.
		async setCaps(caps: Record<string, number>): Promise<void> {
			await submitOrThrow(capsCall, { team: activeTeam.value!, caps })
			await Promise.all([apiKeysCall.reload(), aiCall.reload()])
		},
		capsSaving: computed(() => capsCall.loading),

		// Grove holds the setting: the overview reads it back after the change.
		async setPromptLogging(enabled: boolean): Promise<void> {
			await submitOrThrow(promptLoggingCall, {
				team: activeTeam.value!,
				enabled,
			})
			await aiCall.reload()
		},

		// What a key in one geography starts with: the published models of its default group.
		models: computed<AIModel[]>(() => modelsCall.data ?? []),
		modelsLoading: computed(() => modelsCall.loading),
		modelsError: computed(() => modelsCall.error),
		loadModels(geography: string): Promise<unknown> {
			modelsParams.value = { team: activeTeam.value!, geography }
			return modelsCall.reload()
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

		// Grove pulls the team's gateways now, then every "as of" on the page moves.
		async refreshUsage(): Promise<void> {
			await submitOrThrow(pullCall, { team: activeTeam.value! })
			await Promise.all([
				aiCall.reload(),
				apiKeysCall.reload(),
				usageParams.value.team ? usageCall.reload() : null,
			])
		},
		refreshing: computed(() => pullCall.loading),
	}
}
