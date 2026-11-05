import { frappeRequest } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, isAbortError } from '@/lib/feedback'
import type { BucketObject, BucketObjectPage } from '@/types/storage'

const STORAGE_ERRORS: Record<string, string> = {
	ObjectStorageNotFound: "This bucket doesn't exist in Object Storage.",
	ObjectStorageRejected:
		"Object Storage refused the request. The bucket's key may be out of date.",
	ObjectStorageConnectionError:
		"Object Storage couldn't be reached. Try again in a moment.",
}

const storageError = (failure: unknown): string =>
	STORAGE_ERRORS[(failure as { exc_type?: string })?.exc_type ?? ''] ??
	getErrorMessage(failure, "The files couldn't load.")

export const PAGE_SIZE = 20

// S3's limit for one PUT. Larger files need a multipart upload.
export const MAXIMUM_UPLOAD_BYTES = 5 * 1024 ** 3

// XMLHttpRequest, because fetch cannot report upload progress.
const putFile = (
	url: string,
	file: File,
	contentType: string,
	onProgress: (fraction: number) => void,
	signal: AbortSignal,
): Promise<void> =>
	new Promise((resolve, reject) => {
		if (signal.aborted) {
			reject(new DOMException('Upload cancelled', 'AbortError'))
			return
		}

		const request = new XMLHttpRequest()
		request.open('PUT', url)
		request.setRequestHeader('Content-Type', contentType)
		request.upload.onprogress = (event) => {
			if (event.lengthComputable) onProgress(event.loaded / event.total)
		}
		request.onload = () =>
			request.status < 300
				? resolve()
				: reject(
						new Error(`Object Storage refused the upload (${request.status}).`),
					)
		request.onerror = () =>
			reject(new Error(STORAGE_ERRORS.ObjectStorageConnectionError))
		request.onabort = () =>
			reject(new DOMException('Upload cancelled', 'AbortError'))
		signal.addEventListener('abort', () => request.abort(), { once: true })
		request.send(file)
	})

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

		upload: async (
			name: string,
			key: string,
			file: File,
			onProgress: (fraction: number) => void,
			signal: AbortSignal,
		): Promise<void> => {
			const contentType = file.type || 'application/octet-stream'

			try {
				const { url } = await frappeRequest<{ url: string }>({
					url: methodV1(API.bucketUploadUrl),
					method: 'POST',
					params: {
						team: activeTeam.value,
						name,
						key,
						content_type: contentType,
					},
				})
				await putFile(url, file, contentType, onProgress, signal)
			} catch (failure) {
				if (isAbortError(failure)) throw failure
				throw new Error(storageError(failure))
			}
		},

		remove: async (
			name: string,
			keys: string[],
			prefixes: string[],
		): Promise<number> => {
			try {
				return (
					await frappeRequest<{ deleted: number }>({
						url: methodV1(API.deleteBucketObjects),
						method: 'POST',
						params: { team: activeTeam.value, name, keys, prefixes },
					})
				).deleted
			} catch (failure) {
				throw new Error(storageError(failure))
			}
		},
	}
}
