import { dayjs } from 'frappe-ui'
import { computed, type Ref } from 'vue'
import { LONGEST_METRICS_SECONDS } from '@/lib/serverMetrics'
import type { MetricsRange } from '@/types/servers'

const SITE_CLOCK = 'YYYY-MM-DD HH:mm:ss'

const onSiteClock = (time?: number) => {
	const value = dayjs(time)
	return window.system_timezone ? value.tz(window.system_timezone) : value
}

const fromSiteClock = (text: string): number =>
	(window.system_timezone
		? dayjs.tz(text, window.system_timezone)
		: dayjs(text)
	).valueOf()

/** The usage range that the dropdown, the date pickers and a chart zoom all set. */
export function useMetricsRange(
	range: Ref<MetricsRange>,
	getSampleInterval: () => number | undefined,
) {
	const isCustom = computed(() => range.value.period === 'custom')

	const setRange = (change: Partial<MetricsRange>): void => {
		range.value = { ...range.value, ...change }
	}

	const choosePeriod = (value: string): void => {
		if (value !== 'custom') {
			setRange({ period: value })
			return
		}

		const now = onSiteClock()
		setRange({
			period: value,
			start: now.startOf('day').format(SITE_CLOCK),
			end: now.format(SITE_CLOCK),
		})
	}

	// A drag or a pinch on a chart sets the same range the pickers and the dropdown set,
	// so every chart refetches at the grain the new window needs.
	const zoomTo = ({ start, end }: { start: number; end: number }): void => {
		const to = Math.min(end, Math.floor(Date.now() / 1000))
		const span = to - start
		if (span < 2 * (getSampleInterval() ?? 300)) return

		const zoomed = Math.min(span, LONGEST_METRICS_SECONDS)
		setRange({
			period: 'custom',
			start: onSiteClock((to - zoomed) * 1000).format(SITE_CLOCK),
			end: onSiteClock(to * 1000).format(SITE_CLOCK),
		})
	}

	const visibleWindow = computed(() => {
		const { start, end } = range.value
		if (!isCustom.value || !start || !end) return undefined

		const bounds = { start: fromSiteClock(start), end: fromSiteClock(end) }
		return bounds.end > bounds.start ? bounds : undefined
	})

	return { isCustom, setRange, choosePeriod, zoomTo, visibleWindow }
}
