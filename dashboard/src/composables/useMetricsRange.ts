import { dayjs } from 'frappe-ui'
import { computed, type Ref, ref } from 'vue'
import { LONGEST_METRICS_SECONDS } from '@/lib/serverMetrics'
import type { MetricsRange } from '@/types/servers'

const SITE_CLOCK = 'YYYY-MM-DD HH:mm:ss'

type ZoomWindow = { start: number; end: number }

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
	const preview = ref<ZoomWindow | null>(null)

	const setRange = (change: Partial<MetricsRange>): void => {
		preview.value = null
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

	const fitZoom = ({ start, end }: ZoomWindow): ZoomWindow | null => {
		const to = Math.min(end, Math.floor(Date.now() / 1000))
		const span = to - start
		if (span < 2 * (getSampleInterval() ?? 300)) return null

		return { start: to - Math.min(span, LONGEST_METRICS_SECONDS), end: to }
	}

	const previewZoom = (window: ZoomWindow): void => {
		preview.value = fitZoom(window) ?? preview.value
	}

	// A drag or a pinch on a chart sets the same range the pickers and the dropdown set,
	// so every chart refetches at the grain the new window needs.
	const zoomTo = (window: ZoomWindow): void => {
		const zoomed = fitZoom(window) ?? preview.value
		preview.value = null
		if (!zoomed) return

		setRange({
			period: 'custom',
			start: onSiteClock(zoomed.start * 1000).format(SITE_CLOCK),
			end: onSiteClock(zoomed.end * 1000).format(SITE_CLOCK),
		})
	}

	const visibleWindow = computed(() => {
		if (preview.value)
			return {
				start: preview.value.start * 1000,
				end: preview.value.end * 1000,
			}

		const { start, end } = range.value
		if (!isCustom.value || !start || !end) return undefined

		const bounds = { start: fromSiteClock(start), end: fromSiteClock(end) }
		return bounds.end > bounds.start ? bounds : undefined
	})

	return {
		isCustom,
		setRange,
		choosePeriod,
		zoomTo,
		previewZoom,
		visibleWindow,
	}
}
