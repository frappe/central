import { call, frappeRequest } from 'frappe-ui'
import { onScopeDispose, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { IdleSleepState } from '@/types/servers'

export function useServerIdleSleep(resourceId: Ref<string>) {
	const { activeTeam } = useSession()
	const seconds = ref<number | null>(null)
	const loading = ref(false)
	const saving = ref(false)
	const error = ref('')
	let generation = 0

	async function refresh() {
		const current = ++generation
		seconds.value = null
		error.value = ''
		loading.value = false
		if (!activeTeam.value) return
		loading.value = true
		try {
			const result = await frappeRequest<IdleSleepState>({
				url: methodV1(API.getIdleSleep),
				method: 'GET',
				params: { team: activeTeam.value, resource_id: resourceId.value },
			})
			if (current === generation)
				seconds.value = result.sleep_after_idle_seconds
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					"The sleep setting couldn't be loaded.",
				)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	async function save(value: number): Promise<boolean> {
		if (saving.value || !activeTeam.value) return false
		const current = ++generation
		loading.value = false
		saving.value = true
		error.value = ''
		try {
			await call(API.setIdleSleep, {
				team: activeTeam.value,
				resource_id: resourceId.value,
				seconds: value,
			})
			if (current === generation) seconds.value = value
			return current === generation
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					"The sleep setting couldn't be saved. Try again.",
				)
			return false
		} finally {
			saving.value = false
		}
	}

	watch([activeTeam, resourceId], refresh, { immediate: true })
	onScopeDispose(() => {
		generation++
	})
	return { seconds, loading, saving, error, refresh, save }
}
