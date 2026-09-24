import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type {
	BucketCredentials,
	BucketUsage,
	ObjectStorage,
	StorageBucket,
} from '@/types/storage'

const { activeTeam } = useSession()

const storageCall = useCall<ObjectStorage, { team: string }>({
	url: method(API.objectStorage),
	params: teamParams,
	immediate: false,
	refetch: true,
})

whenTeamReady(() => storageCall.reload())

const usageName = ref('')
const usageCall = useCall<BucketUsage, { team: string; name: string }>({
	url: method(API.bucketUsage),
	params: () => ({ team: activeTeam.value!, name: usageName.value }),
	immediate: false,
})

const createCall = useCall<
	BucketCredentials,
	{ team: string; bucket_name: string; region: string }
>({ url: method(API.createBucket), method: 'POST', immediate: false })

const rotateCall = useCall<BucketCredentials, { team: string; name: string }>({
	url: method(API.rotateBucketCredentials),
	method: 'POST',
	immediate: false,
})

const quotaCall = useCall<
	{ name: string },
	{ team: string; name: string; size_gib: number; max_objects: number }
>({ url: method(API.setBucketQuota), method: 'POST', immediate: false })

const deleteCall = useCall<{ name: string }, { team: string; name: string }>({
	url: method(API.deleteBucket),
	method: 'POST',
	immediate: false,
})

export const bucketLabel = (bucket: StorageBucket): string =>
	bucket.is_managed
		? 'Server backups'
		: bucket.bucket_name.replace(new RegExp(`^\\d+-${bucket.region}-`), '')

export const useObjectStorage = () => ({
	regions: computed(() => storageCall.data?.regions ?? []),
	buckets: computed(() => storageCall.data?.buckets ?? []),
	loading: computed(() => storageCall.loading && !storageCall.data),
	error: computed(() => storageCall.error),
	reload: () => storageCall.reload(),

	usage: computed(() => usageCall.data),
	usageLoading: computed(() => usageCall.loading),
	usageError: computed(() => usageCall.error),
	loadUsage: (name: string) => {
		usageName.value = name
		return usageCall.reload()
	},

	createBucket: async (
		bucketName: string,
		region: string,
	): Promise<BucketCredentials> => {
		await submitOrThrow(createCall, {
			team: activeTeam.value!,
			bucket_name: bucketName,
			region,
		})
		await storageCall.reload()
		return createCall.data!
	},

	rotateCredentials: async (name: string): Promise<BucketCredentials> => {
		await submitOrThrow(rotateCall, { team: activeTeam.value!, name })
		await storageCall.reload()
		return rotateCall.data!
	},

	setQuota: async (
		name: string,
		sizeGib: number,
		maxObjects: number,
	): Promise<void> => {
		await submitOrThrow(quotaCall, {
			team: activeTeam.value!,
			name,
			size_gib: sizeGib,
			max_objects: maxObjects,
		})
		successToast('Quota saved')
		await usageCall.reload()
	},

	deleteBucket: async (name: string): Promise<void> => {
		await submitOrThrow(deleteCall, { team: activeTeam.value!, name })
		successToast('Bucket deleted')
		await storageCall.reload()
	},
})
