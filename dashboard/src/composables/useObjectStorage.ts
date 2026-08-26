import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { submitOrThrow } from '@/lib/frappeCall'
import { errorToast, successToast } from '@/lib/toast'

// The team's object-storage buckets. Central creates and names them, mints a key
// scoped to each, and shows both halves; whoever holds them configures their own
// bench by hand. Revoking a key leaves the bucket and its objects untouched. Team
// activation lives in `useServices`, shared with every other add-on.

// A bucket, as listed (no secret).
export interface StorageBucket {
	name: string
	label: string
	status: string
	gateway_url: string | null
	provider_ref: string | null
	service_backend: string | null
	region: string | null
	creation: string
	masked_key: string
}

// The endpoint and both key halves, returned on create and on reveal. S3 needs all four.
export interface RevealedBucket {
	name: string
	bucket: string
	endpoint_url: string
	access_key_id: string
	secret_access_key: string
}

const { activeTeam } = useSession()
const managedRef = ref('')

const bucketsCall = useCall<StorageBucket[], { managed_service: string }>({
	url: method(API.listBuckets),
	params: () => ({ managed_service: managedRef.value }),
	immediate: false,
})

const createCall = useCall<
	RevealedBucket & { status: string },
	{ team: string; bucket: string }
>({ url: method(API.createBucket), method: 'POST', immediate: false })

const revealCall = useCall<RevealedBucket, { name: string }>({
	url: method(API.revealBucketKey),
	method: 'POST',
	immediate: false,
})

const revokeCall = useCall<{ name: string; status: string }, { name: string }>({
	url: method(API.revokeBucketKey),
	method: 'POST',
	immediate: false,
})

// Row-level busy: the bucket currently mutating, so its control alone spins.
const busyBucket = ref('')

function reloadBuckets(): Promise<unknown> | void {
	if (managedRef.value) return bucketsCall.reload()
}

export function useObjectStorage() {
	return {
		buckets: computed(() => bucketsCall.data ?? []),
		bucketsLoading: computed(() => bucketsCall.loading),
		busyBucket: computed(() => busyBucket.value),

		loadBuckets(managedService: string): Promise<unknown> {
			managedRef.value = managedService
			return bucketsCall.reload()
		},

		// Create and reveal throw so the caller can show the credentials itself.
		async createBucket(bucket: string): Promise<RevealedBucket> {
			await submitOrThrow(createCall, { team: activeTeam.value!, bucket })
			await reloadBuckets()
			return createCall.data!
		},

		async revealBucketKey(name: string): Promise<RevealedBucket> {
			await submitOrThrow(revealCall, { name })
			return revealCall.data!
		},

		// Revoke follows the toast + reload row pattern.
		async revokeBucketKey(name: string): Promise<void> {
			busyBucket.value = name
			try {
				await submitOrThrow(revokeCall, { name })
				successToast('Bucket key revoked')
				await reloadBuckets()
			} catch (e) {
				errorToast(e)
			} finally {
				busyBucket.value = ''
			}
		},
	}
}
