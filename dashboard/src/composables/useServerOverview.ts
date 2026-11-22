import { useCall } from 'frappe-ui'
import { computed, type Ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, isAbortError } from '@/lib/feedback'
import { LONGEST_METRICS_SECONDS } from '@/lib/serverMetrics'
import { __ } from '@/lib/translate'
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

	const asTime = (value: string) => Date.parse(value.replace(' ', 'T'))

	const rangeError = computed(() => {
		const { period, start, end } = range.value
		if (period !== 'custom' || !start || !end) return ''

		const from = asTime(start)
		const to = asTime(end)
		if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) {
			return __('The end must be after the start.')
		}

		return to - from > LONGEST_METRICS_SECONDS * 1000
			? __('Choose {0} days or less.', [LONGEST_METRICS_SECONDS / 86400])
			: ''
	})

	const reloadMetrics = (): void => {
		const { period, start, end } = range.value
		const isCustom = period === 'custom'
		const isComplete = !isCustom || (!!start && !!end)
		if (
			!activeTeam.value ||
			rangeError.value ||
			(!isComplete && metricsCall.data)
		)
			return

		metricsCall.submit({
			team: activeTeam.value,
			resource_id: resourceId.value,
			period: isComplete ? period : '1h',
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
		metricsLoading: computed(() => metricsCall.loading),
		metricsError: computed(() =>
			metricsCall.error && !isAbortError(metricsCall.error)
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
		rangeError,
	}
}
