import { useCall } from 'frappe-ui'
import { computed, type Ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type {
	MetricsRange,
	ServerMonitoring,
	ServerOverview,
} from '@/types/servers'

export const useServerOverview = (
	resourceId: Ref<string>,
	range: Ref<MetricsRange>,
) => {
	const { activeTeam } = useSession()

	const overviewCall = useCall<
		ServerOverview,
		{ team: string; resource_id: string }
	>({
		url: method(API.serverOverview),
		method: 'GET',
		immediate: false,
	})

	const metricsCall = useCall<
		ServerMonitoring,
		{
			team: string
			resource_id: string
			period: string
			start?: string
			end?: string
		}
	>({
		url: method(API.serverMetrics),
		method: 'GET',
		immediate: false,
	})

	const reload = (): void => {
		if (!activeTeam.value) return

		overviewCall.submit({
			team: activeTeam.value,
			resource_id: resourceId.value,
		})
	}

	const reloadMetrics = (): void => {
		const { period, start, end } = range.value
		const isCustom = period === 'custom'
		const isComplete = !isCustom || (!!start && !!end)
		if (!activeTeam.value || (!isComplete && metricsCall.data)) return

		metricsCall.submit({
			team: activeTeam.value,
			resource_id: resourceId.value,
			period: isComplete ? period : '24h',
			...(isCustom &&
				isComplete && { start: start ?? undefined, end: end ?? undefined }),
		})
	}

	watch([activeTeam, resourceId], reload, { immediate: true })

	watch(
		[
			activeTeam,
			resourceId,
			() => range.value.period,
			() => range.value.start,
			() => range.value.end,
		],
		reloadMetrics,
		{ immediate: true },
	)

	return {
		overview: computed(() => overviewCall.data),
		metrics: computed(() => metricsCall.data),
		metricsError: computed(() =>
			metricsCall.error
				? getErrorMessage(metricsCall.error, "Usage couldn't load.")
				: '',
		),
		loading: computed(() => overviewCall.loading),
		error: computed(() =>
			overviewCall.error
				? getErrorMessage(overviewCall.error, "This server couldn't load.")
				: '',
		),
		reload,
		reloadMetrics,
	}
}
