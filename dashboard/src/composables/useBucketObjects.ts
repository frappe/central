import { frappeRequest } from 'frappe-ui'
import { ref } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { BucketObject, BucketObjectPage } from '@/types/storage'

const STORAGE_ERRORS: Record<string, string> = {
	ObjectStorageNotFound: "This bucket doesn't exist in object storage.",
	ObjectStorageRejected:
		"Object storage refused the request. The bucket's key may be out of date.",
	ObjectStorageConnectionError:
		"Object storage couldn't be reached. Try again in a moment.",
}

const storageError = (failure: unknown): string =>
	STORAGE_ERRORS[(failure as { exc_type?: string })?.exc_type ?? ''] ??
	getErrorMessage(failure, "The files couldn't load.")

export const useBucketObjects = () => {
	const { activeTeam } = useSession()
	const objects = ref<BucketObject[]>([])
	const folders = ref<string[]>([])
	const nextOffset = ref<string | null>(null)
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	const fetchPage = async (
		name: string,
		prefix: string,
		offset: string | null,
	): Promise<void> => {
		const current = ++generation
		loading.value = true
		error.value = ''
		try {
			const page = await frappeRequest<BucketObjectPage>({
				url: methodV1(API.listBucketObjects),
				method: 'GET',
				params: {
					team: activeTeam.value,
					name,
					prefix,
					...(offset && { offset }),
				},
			})
			if (current !== generation) return
			objects.value = offset ? [...objects.value, ...page.objects] : page.objects
			folders.value = offset ? [...folders.value, ...page.folders] : page.folders
			nextOffset.value = page.next_offset
		} catch (failure) {
			if (current === generation)
				error.value = storageError(failure)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	return {
		objects,
		folders,
		nextOffset,
		loading,
		error,
		load: (name: string, prefix: string) => fetchPage(name, prefix, null),
		loadMore: (name: string, prefix: string) =>
			fetchPage(name, prefix, nextOffset.value),
		getDownloadUrl: async (name: string, key: string): Promise<string> =>
			(
				await frappeRequest<{ url: string }>({
					url: methodV1(API.bucketObjectUrl),
					method: 'GET',
					params: { team: activeTeam.value, name, key },
				})
			).url,
	}
}
