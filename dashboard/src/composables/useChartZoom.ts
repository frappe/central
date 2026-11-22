import { computed, onBeforeUnmount, ref, useTemplateRef } from 'vue'
import type { MetricRow } from '@/lib/serverMetrics'

type AreaChartApi = {
	chart?: {
		getDom: () => HTMLElement
		convertFromPixel: (
			finder: { seriesIndex: number },
			pixel: number[],
		) => number[]
	}
}

type Band = {
	left: number
	width: number
	start: number | null
	end: number | null
}

type ZoomWindow = { start: number; end: number }

/** Drag, pinch or ctrl-scroll zoom on one time-axis chart. Each zoom reports its window in seconds. */
export function useChartZoom(
	getRows: () => MetricRow[],
	getVisibleWindow: () => ZoomWindow | undefined,
	report: {
		zoom: (window: ZoomWindow) => void
		preview: (window: ZoomWindow) => void
	},
) {
	const plot = useTemplateRef<AreaChartApi>('plot')
	const plotBox = useTemplateRef<HTMLElement>('plotBox')
	const band = ref<Band | null>(null)
	const MIN_DRAG_PIXELS = 8
	const WHEEL_STEP = 1.15
	let dragStart: number | null = null
	let wheelTimer: ReturnType<typeof setTimeout> | undefined
	let pinch: { base: [number, number]; at: number; factor: number } | null =
		null

	const getChart = () => plot.value?.chart

	// Pointer position in the plot's own pixels, which is what echarts converts.
	const chartX = (event: MouseEvent): number | null => {
		const dom = getChart()?.getDom()
		return dom ? event.clientX - dom.getBoundingClientRect().left : null
	}

	const timeAt = (event: MouseEvent): number | null => {
		const x = chartX(event)
		const at =
			x === null
				? null
				: getChart()?.convertFromPixel({ seriesIndex: 0 }, [x, 0])?.[0]
		return at !== null && at !== undefined && Number.isFinite(at) ? at : null
	}

	const rowsWindow = (): [number, number] | null => {
		const rows = getRows()
		const first = rows[0]?.time
		const last = rows[rows.length - 1]?.time
		if (!(first instanceof Date) || !(last instanceof Date)) return null
		return [first.getTime(), last.getTime()]
	}

	const shownWindow = (): [number, number] | null => {
		const visible = getVisibleWindow()
		return visible ? [visible.start, visible.end] : rowsWindow()
	}

	// Zoom keeps the timestamp under the pointer in place, so the chart grows or shrinks around it.
	const windowAround = (
		[first, last]: [number, number],
		at: number,
		factor: number,
	): ZoomWindow => {
		const span = Math.max(60_000, last - first)
		const anchor = Math.min(Math.max(at, first), last)
		const width = span * factor
		const start = anchor - width * ((anchor - first) / span)

		return {
			start: Math.floor(start / 1000),
			end: Math.ceil((start + width) / 1000),
		}
	}

	const wheelZoom = (event: WheelEvent): void => {
		if (!event.ctrlKey || !getChart()) return

		// A trackpad pinch arrives as ctrl + wheel. Stopping the default keeps the page still.
		event.preventDefault()
		globalThis.clearTimeout?.(wheelTimer)

		if (!pinch) {
			const base = shownWindow()
			const at = timeAt(event)
			if (!base || at === null) return
			pinch = { base, at, factor: 1 }
		}

		pinch.factor *= event.deltaY > 0 ? WHEEL_STEP : 1 / WHEEL_STEP
		const window = windowAround(pinch.base, pinch.at, pinch.factor)

		// The axis follows every tick; the request waits until the pinch pauses.
		report.preview(window)
		wheelTimer = globalThis.setTimeout(() => {
			pinch = null
			report.zoom(window)
		}, 250)
	}

	onBeforeUnmount(() => globalThis.clearTimeout?.(wheelTimer))

	const startZoom = (event: PointerEvent): void => {
		if (!event.isPrimary || event.button !== 0 || !getChart() || !plotBox.value)
			return

		dragStart = chartX(event)
		if (dragStart === null) return

		plotBox.value.setPointerCapture(event.pointerId)
		band.value = {
			left: event.clientX - plotBox.value.getBoundingClientRect().left,
			width: 0,
			start: timeAt(event),
			end: timeAt(event),
		}
	}

	const moveZoom = (event: PointerEvent): void => {
		if (dragStart === null || !plotBox.value) return

		const start = band.value?.left ?? 0
		const x = event.clientX - plotBox.value.getBoundingClientRect().left
		band.value = {
			left: Math.min(start, x),
			width: Math.abs(x - start),
			start: dragStart <= x ? (band.value?.start ?? null) : timeAt(event),
			end: dragStart <= x ? timeAt(event) : (band.value?.end ?? null),
		}
	}

	const finishZoom = (event: PointerEvent): void => {
		const from = dragStart
		const selection = band.value
		const width = selection?.width ?? 0
		dragStart = null
		band.value = null

		if (from === null || !getChart() || width < MIN_DRAG_PIXELS) return

		const chart = getChart()
		const to = chartX(event)
		if (!chart || to === null) return

		// A time axis answers in milliseconds, so the payload is seconds like the samples.
		const edges = [from, to].map(
			(x) => chart.convertFromPixel({ seriesIndex: 0 }, [x, 0])?.[0] / 1000,
		)
		if (!edges.every(Number.isFinite) || edges[1] - edges[0] <= 0) return

		report.zoom({ start: Math.floor(edges[0]), end: Math.ceil(edges[1]) })
	}

	const formatSpan = (seconds: number): string => {
		const minutes = Math.max(1, Math.round(seconds / 60))
		if (minutes < 60) return `${minutes} min`

		const hours = Math.floor(minutes / 60)
		if (hours < 24)
			return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`

		const days = Math.floor(hours / 24)
		return hours % 24 ? `${days} d ${hours % 24} h` : `${days} d`
	}

	const bandSpan = computed(() => {
		const { start, end } = band.value ?? {}

		return start && end ? formatSpan(Math.abs(end - start) / 1000) : ''
	})

	return {
		band,
		bandSpan,
		wheelZoom,
		startZoom,
		moveZoom,
		finishZoom,
	}
}
