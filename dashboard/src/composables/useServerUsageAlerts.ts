import { call, frappeRequest } from 'frappe-ui'
import { onScopeDispose, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { UsageAlertLimits } from '@/types/servers'

const LIMIT_KEYS = [
	'cpu_usage_limit',
	'memory_usage_limit',
	'disk_space_limit',
] as const

export const USAGE_ALERT_MAXIMUM = 95

/** A whole percentage from 1 to the maximum, or 0 for off; null when invalid. */
export function parseUsageAlertLimit(value: string): number | null {
	const trimmed = String(value).trim()
	if (!/^\d+$/.test(trimmed)) return null
	const percent = Number(trimmed)
	return percent <= USAGE_ALERT_MAXIMUM ? percent : null
}

export function useServerUsageAlerts(resourceId: Ref<string>) {
	const { activeTeam } = useSession()
	const limits = ref<UsageAlertLimits | null>(null)
	const loading = ref(false)
	const saving = ref(false)
	const error = ref('')
	let generation = 0

	async function refresh() {
		const current = ++generation
		limits.value = null
		error.value = ''
		loading.value = false
		if (!activeTeam.value) return
		loading.value = true
		try {
			const result = await frappeRequest<UsageAlertLimits>({
				url: methodV1(API.getUsageAlertLimits),
				method: 'GET',
				params: { team: activeTeam.value, resource_id: resourceId.value },
			})
			if (current === generation) limits.value = result
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					"The usage alerts couldn't be loaded.",
				)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	function changedLimits(next: UsageAlertLimits): Partial<UsageAlertLimits> {
		const changed: Partial<UsageAlertLimits> = {}
		for (const key of LIMIT_KEYS) {
			if (next[key] !== limits.value?.[key]) changed[key] = next[key]
		}
		return changed
	}

	async function save(next: UsageAlertLimits): Promise<boolean> {
		if (saving.value || !activeTeam.value) return false
		const changed = changedLimits(next)
		if (!Object.keys(changed).length) return true
		const current = ++generation
		loading.value = false
		saving.value = true
		error.value = ''
		try {
			await call(API.setUsageAlertLimits, {
				team: activeTeam.value,
				resource_id: resourceId.value,
				limits: changed,
			})
			if (current === generation && limits.value)
				limits.value = { ...limits.value, ...changed }
			return current === generation
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					"The usage alerts couldn't be saved. Try again.",
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
	return { limits, loading, saving, error, refresh, save }
}
