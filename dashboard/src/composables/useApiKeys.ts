import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { submitOrThrow } from '@/lib/frappeCall'
import type { ApiKeyList, NewApiKey } from '@/types/apiKeys'

const listCall = useCall<ApiKeyList>({
	url: method(API.apiKeys),
	immediate: false,
})

const createCall = useCall<{ name: string; token: string }, NewApiKey>({
	url: method(API.createApiKey),
	method: 'POST',
	immediate: false,
})

const revokeCall = useCall<null, { name: string }>({
	url: method(API.revokeApiKey),
	method: 'POST',
	immediate: false,
})

/** Create a key and return its token, which the server never shows again. */
async function create(key: NewApiKey): Promise<string> {
	await submitOrThrow(createCall, key)
	const token = createCall.data!.token
	void listCall.reload()

	return token
}

async function revoke(name: string): Promise<void> {
	await submitOrThrow(revokeCall, { name })
	await listCall.reload()
}

/** The signed-in user's API keys across their teams. */
export function useApiKeys() {
	return {
		keys: computed(() => listCall.data?.keys ?? []),
		scopes: computed(() => listCall.data?.scopes ?? {}),
		expiryDays: computed(() => listCall.data?.expiry_days ?? []),
		loading: computed(() => listCall.loading),
		error: computed(() => listCall.error),
		creating: computed(() => createCall.loading),
		revoking: computed(() => revokeCall.loading),
		reload: () => listCall.reload(),
		create,
		revoke,
	}
}
