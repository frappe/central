import { call, frappeRequest } from 'frappe-ui'
import { onScopeDispose, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { RescueState } from '@/types/servers'

export function useServerRescue(resourceId: Ref<string>) {
	const { activeTeam } = useSession()
	const state = ref<RescueState | null>(null)
	const loading = ref(false)
	const saving = ref(false)
	const error = ref('')
	let generation = 0

	async function refresh() {
		const current = ++generation
		state.value = null
		error.value = ''
		loading.value = false
		if (!activeTeam.value) return
		loading.value = true
		try {
			const result = await frappeRequest<RescueState>({
				url: methodV1(API.getRescueState),
				method: 'GET',
				params: { team: activeTeam.value, resource_id: resourceId.value },
			})
			if (current === generation) state.value = result
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					"Rescue status couldn't be loaded.",
				)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	async function select(enabled: boolean) {
		if (saving.value || !activeTeam.value) return
		const current = ++generation
		loading.value = false
		const team = activeTeam.value
		const server = resourceId.value
		saving.value = true
		error.value = ''
		try {
			await call(API.setRescueMode, { team, resource_id: server, enabled })
			if (current !== generation) return
			await refresh()
			return true
		} catch (failure) {
			if (current !== generation) return
			state.value = null
			error.value = getErrorMessage(
				failure,
				"The boot selection couldn't be confirmed. Reload the page before you try again.",
			)
		} finally {
			saving.value = false
		}
	}

	watch([activeTeam, resourceId], refresh, { immediate: true })
	onScopeDispose(() => {
		generation++
	})
	return { state, loading, saving, error, refresh, select }
}
