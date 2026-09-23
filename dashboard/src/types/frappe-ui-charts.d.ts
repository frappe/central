import type { Component } from 'vue'

export interface ChartTooltipItem {
	name?: string
	value?: number | string
	color?: string
	[key: string]: unknown
}

export const BarChart: Component
export const ChartTooltip: Component
export const DonutChart: Component
export const LineChart: Component
export const NumberCard: Component
