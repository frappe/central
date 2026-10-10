import type { Component, Ref } from 'vue'

export interface ChartTooltipItem {
	name?: string
	value?: number | string
	color?: string
	[key: string]: unknown
}

export const AreaChart: Component
export const BarChart: Component
export const ChartCard: Component
export const ChartTooltip: Component
export const DonutChart: Component
export const LineChart: Component
export const NumberCard: Component

export const useChartTokens: (element: Ref<HTMLElement | undefined>) => {
	tokens: Ref<{ categorical: string[] }>
}
