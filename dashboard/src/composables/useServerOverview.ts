import { useCall } from 'frappe-ui'
import { computed, type Ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { MetricsRange, ServerOverview } from '@/types/servers'

export const useServerOverview = (
	resourceId: Ref<string>,
	range: Ref<MetricsRange>,
) => {
	const { activeTeam } = useSession()

	const overviewCall = useCall<
		ServerOverview,
		{
			team: string
			resource_id: string
			period: string
			start?: string
			end?: string
		}
	>({
		url: method(API.serverOverview),
		method: 'GET',
		immediate: false,
	})

	const reload = (): void => {
		const { period, start, end } = range.value
		const isCustom = period === 'custom'
		const isComplete = !isCustom || (!!start && !!end)
		if (!activeTeam.value || (!isComplete && overviewCall.data)) return

		overviewCall.submit({
			team: activeTeam.value,
			resource_id: resourceId.value,
			period: isComplete ? period : '24h',
			...(isCustom &&
				isComplete && { start: start ?? undefined, end: end ?? undefined }),
		})
	}

	watch(
		[
			activeTeam,
			resourceId,
			() => range.value.period,
			() => range.value.start,
			() => range.value.end,
		],
		reload,
		{ immediate: true },
	)

	return {
		overview: computed(() => overviewCall.data),
		loading: computed(() => overviewCall.loading),
		error: computed(() =>
			overviewCall.error
				? getErrorMessage(overviewCall.error, "This server couldn't load.")
				: '',
		),
		reload,
	}
}
