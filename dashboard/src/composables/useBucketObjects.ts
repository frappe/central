import { frappeRequest } from 'frappe-ui'
import { computed, ref } from 'vue'
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

export const PAGE_SIZE = 20

export const useBucketObjects = () => {
	const { activeTeam } = useSession()
	const objects = ref<BucketObject[]>([])
	const folders = ref<string[]>([])
	const cursors = ref<(string | null)[]>([null])
	const page = ref(0)
	const nextOffset = ref<string | null>(null)
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	const fetchPage = async (name: string, prefix: string): Promise<void> => {
		const current = ++generation
		const offset = cursors.value[page.value]

		loading.value = true
		error.value = ''

		try {
			const result = await frappeRequest<BucketObjectPage>({
				url: methodV1(API.listBucketObjects),
				method: 'GET',
				params: {
					team: activeTeam.value,
					name,
					prefix,
					limit: PAGE_SIZE,
					...(offset && { offset }),
				},
			})

			if (current !== generation) return

			objects.value = result.objects
			folders.value = result.folders
			nextOffset.value = result.next_offset
		} catch (failure) {
			if (current === generation) error.value = storageError(failure)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	return {
		objects,
		folders,
		page,
		loading,
		error,
		hasNext: computed(() => !!nextOffset.value),
		load: (name: string, prefix: string) => {
			cursors.value = [null]
			page.value = 0
			return fetchPage(name, prefix)
		},

		next: (name: string, prefix: string) => {
			cursors.value = [
				...cursors.value.slice(0, page.value + 1),
				nextOffset.value,
			]
			page.value += 1
			return fetchPage(name, prefix)
		},

		previous: (name: string, prefix: string) => {
			page.value -= 1
			return fetchPage(name, prefix)
		},
		retry: (name: string, prefix: string) => fetchPage(name, prefix),

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
