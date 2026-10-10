import {
	type CSSProperties,
	computed,
	onBeforeUnmount,
	onMounted,
	type Ref,
	ref,
	watch,
} from 'vue'
import { MAP_HEIGHT, MAP_WIDTH } from '@/lib/serverMap'

interface MapPoint {
	x: number
	y: number
}

const MAX_FIT_ZOOM = 1.8
const GLIDE_MS = 600

/**
 * The map's viewport: contain-fits the world into `element`, then frames `getFrame()`.
 * The first fit and every resize land in place; later reframes glide.
 */
export function useMapViewport(
	element: Ref<HTMLElement | null>,
	getFrame: () => MapPoint[],
	framePadding: () => number,
) {
	const width = ref(0)
	const height = ref(0)
	const zoom = ref(1)
	const offsetX = ref(0)
	const offsetY = ref(0)
	const isGliding = ref(false)
	// CSS transitions stay off until the first layout and during a resize.
	const isReady = ref(false)
	const isResizing = ref(false)

	const baseScale = computed(() =>
		width.value && height.value
			? Math.min(width.value / MAP_WIDTH, height.value / MAP_HEIGHT)
			: 0,
	)
	const scale = computed(() => baseScale.value * zoom.value)

	// The dotted world is one large SVG path. A resize keeps the last raster and scales it,
	// so the compositor carries the frames; the crisp raster lands once the size settles.
	const rasterScale = ref(0)
	watch([scale, isResizing], () => {
		if (!isResizing.value) rasterScale.value = scale.value
	})

	watch(baseScale, (value) => {
		if (value && !isReady.value)
			requestAnimationFrame(() =>
				requestAnimationFrame(() => (isReady.value = true)),
			)
	})

	let resizeFrame = 0
	function measure(nextWidth: number, nextHeight: number): void {
		if (nextWidth === width.value && nextHeight === height.value) return
		isResizing.value = true
		width.value = nextWidth
		height.value = nextHeight
		cancelAnimationFrame(resizeFrame)
		// Commit the crisp raster first, then re-arm transitions a frame later.
		resizeFrame = requestAnimationFrame(() => {
			rasterScale.value = scale.value
			resizeFrame = requestAnimationFrame(() => (isResizing.value = false))
		})
	}

	function clampOffset(): void {
		const mapWidth = MAP_WIDTH * scale.value
		const mapHeight = MAP_HEIGHT * scale.value
		offsetX.value =
			mapWidth <= width.value
				? (width.value - mapWidth) / 2
				: Math.min(0, Math.max(width.value - mapWidth, offsetX.value))
		offsetY.value =
			mapHeight <= height.value
				? (height.value - mapHeight) / 2
				: Math.min(0, Math.max(height.value - mapHeight, offsetY.value))
	}
	watch([baseScale, width, height], clampOffset)

	let glideFrame = 0
	function cancelGlide(): void {
		cancelAnimationFrame(glideFrame)
		isGliding.value = false
	}

	function centreOn(x: number, y: number, nextZoom: number): void {
		zoom.value = nextZoom
		offsetX.value = width.value / 2 - x * scale.value
		offsetY.value = height.value / 2 - y * scale.value
		clampOffset()
	}

	// One continuous move: zoom interpolates in log space so the path never swings.
	function glideTo(x: number, y: number, nextZoom: number): void {
		cancelGlide()
		const startZoom = zoom.value
		const from = {
			x: x * scale.value + offsetX.value,
			y: y * scale.value + offsetY.value,
		}
		const to = { x: width.value / 2, y: height.value / 2 }
		const start = performance.now()
		const ease = (t: number) =>
			t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
		isGliding.value = true
		const step = (now: number) => {
			const progress = ease(Math.min(1, (now - start) / GLIDE_MS))
			zoom.value = startZoom * (nextZoom / startZoom) ** progress
			offsetX.value = from.x + (to.x - from.x) * progress - x * scale.value
			offsetY.value = from.y + (to.y - from.y) * progress - y * scale.value
			clampOffset()
			if (now - start < GLIDE_MS) glideFrame = requestAnimationFrame(step)
			else isGliding.value = false
		}
		glideFrame = requestAnimationFrame(step)
	}

	function fitFrame(): void {
		if (!baseScale.value) return
		const points = getFrame()
		if (!points.length) {
			if (isReady.value && zoom.value > 1)
				glideTo(MAP_WIDTH / 2, MAP_HEIGHT / 2, 1)
			return
		}
		const xs = points.map((point) => point.x)
		const ys = points.map((point) => point.y)
		const pad = framePadding() * 2
		const fitZoom = Math.min(
			MAX_FIT_ZOOM,
			Math.max(
				1,
				Math.min(
					width.value / (Math.max(...xs) - Math.min(...xs) + pad),
					height.value / (Math.max(...ys) - Math.min(...ys) + pad),
				) / baseScale.value,
			),
		)
		const centreX = (Math.min(...xs) + Math.max(...xs)) / 2
		const centreY = (Math.min(...ys) + Math.max(...ys)) / 2
		if (!isReady.value || isResizing.value) {
			cancelGlide()
			centreOn(centreX, centreY, fitZoom)
		} else glideTo(centreX, centreY, fitZoom)
	}

	// Reloads hand over new arrays of the same places; only a new set of places reframes.
	const frameKey = computed(() =>
		getFrame()
			.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
			.sort()
			.join('|'),
	)
	watch([frameKey, baseScale], fitFrame)

	function toScreen(point: MapPoint): MapPoint {
		return {
			x: offsetX.value + point.x * scale.value,
			y: offsetY.value + point.y * scale.value,
		}
	}

	const mapStyle = computed<CSSProperties>(() => {
		const raster = rasterScale.value || scale.value
		const resizeScale = raster ? scale.value / raster : 1
		const translate = `translate3d(${offsetX.value}px, ${offsetY.value}px, 0)`
		return {
			transform:
				resizeScale === 1 ? translate : `${translate} scale(${resizeScale})`,
			transformOrigin: '0 0',
			width: `${MAP_WIDTH * raster}px`,
			height: `${MAP_HEIGHT * raster}px`,
		}
	})

	let observer: ResizeObserver | undefined
	onMounted(() => {
		// Measure before first paint; the observer's first callback lands a frame late.
		if (!element.value) return
		const rect = element.value.getBoundingClientRect()
		measure(rect.width, rect.height)
		observer = new ResizeObserver(([entry]) =>
			measure(entry.contentRect.width, entry.contentRect.height),
		)
		observer.observe(element.value)
	})
	onBeforeUnmount(() => {
		observer?.disconnect()
		cancelAnimationFrame(glideFrame)
		cancelAnimationFrame(resizeFrame)
	})

	return {
		width,
		height,
		scale,
		isReady,
		isResizing,
		isGliding,
		mapStyle,
		toScreen,
	}
}
