import type { ECharts } from 'echarts/core'
import { onBeforeUnmount, onMounted, type Ref, watch } from 'vue'

type ChartHandle = {
	chart?: ECharts
}

export function useInstantChartResize(
	el: Ref<HTMLElement | null>,
	chart: Ref<ChartHandle | null>,
): void {
	let observer: ResizeObserver | undefined
	let first = true
	let lastWidth = 0
	let lastHeight = 0
	onMounted(() => {
		observer = new ResizeObserver((entries) => {
			const box = entries[entries.length - 1]?.contentRect
			if (!box || (box.width === lastWidth && box.height === lastHeight)) return
			lastWidth = box.width
			lastHeight = box.height
			if (first) {
				first = false
				return
			}
			if (!box.width || !box.height) return
			chart.value?.chart?.resize({ animation: { duration: 0 } })
		})
		if (el.value) observer.observe(el.value)
	})
	watch(el, (node, previous) => {
		if (previous) observer?.unobserve(previous)
		if (node) observer?.observe(node)
	})
	onBeforeUnmount(() => {
		observer?.disconnect()
		observer = undefined
	})
}
