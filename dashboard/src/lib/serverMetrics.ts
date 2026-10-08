import type { MetricPoint } from '@/types/servers'

export type MetricRow = Record<string, Date | number | null>

export interface MetricChart {
	key: string
	title: string
	series: string[]
	colors: number[]
	format: (value: number) => string
	rows: MetricRow[]
}

const RATE_UNITS = ['B/s', 'KB/s', 'MB/s', 'GB/s']

const getRateScale = (values: (number | null)[]) => {
	const peak = Math.max(0, ...values.map((value) => value ?? 0))
	const exponent = Math.min(
		RATE_UNITS.length - 1,
		Math.max(0, Math.floor(Math.log(Math.max(peak, 1)) / Math.log(1024))),
	)

	return { divisor: 1024 ** exponent, unit: RATE_UNITS[exponent] }
}

const scale = (value: number | null, divisor: number) =>
	value == null ? null : value / divisor

const toDate = (seconds: number): Date => new Date(seconds * 1000)

const getRateChart = (
	key: string,
	title: string,
	points: MetricPoint[],
	colors: number[],
	series: Record<string, (point: MetricPoint) => number | null>,
): MetricChart => {
	const rate = getRateScale(
		points.flatMap((point) => Object.values(series).map((read) => read(point))),
	)

	return {
		key,
		title,
		series: Object.keys(series),
		colors,
		format: (value) => `${Number(value.toFixed(1))} ${rate.unit}`,
		rows: points.map((point) => ({
			time: toDate(point.time),
			...Object.fromEntries(
				Object.entries(series).map(([label, read]) => [
					label,
					scale(read(point), rate.divisor),
				]),
			),
		})),
	}
}

export const getChartSummary = (chart: MetricChart): string => {
	const values = chart.rows
		.map((row) => row[chart.series[0]])
		.filter((value): value is number => typeof value === 'number')
	if (!values.length) return ''

	const now = chart.format(values[values.length - 1])
	const peak = chart.format(Math.max(...values))

	return `Now ${now} · Peak ${peak}`
}

export const formatSampleInterval = (seconds: number): string => {
	if (seconds % 3600 === 0)
		return seconds === 3600 ? 'hour' : `${seconds / 3600} hours`

	if (seconds % 60 === 0) return `${seconds / 60} min`

	return `${seconds} sec`
}

export const METRIC_PERIODS = [
	{ label: '24 hours', short: '24h', value: '24h' },
	{ label: '7 days', short: '7d', value: '7d' },
	{ label: '14 days', short: '14d', value: '14d' },
	{ label: '30 days', short: '30d', value: '30d' },
	{ label: 'Custom', short: null, value: 'custom' },
]

export const getChartTimeGrain = (points: MetricPoint[]) => {
	const span = points.length
		? points[points.length - 1].time - points[0].time
		: 0
	if (span <= 86400) return 'minute'

	return span <= 7 * 86400 ? 'hour' : 'day'
}

export const getMetricCharts = (points: MetricPoint[]): MetricChart[] => [
	{
		key: 'cpu',
		title: 'CPU',
		series: ['CPU'],
		colors: [1],
		format: (value) => `${Number(value.toFixed(1))}%`,
		rows: points.map((point) => ({
			time: toDate(point.time),
			CPU: point.cpu_percent,
		})),
	},
	{
		key: 'memory',
		title: 'Memory',
		series: ['Used'],
		colors: [5],
		format: (value) => `${Number(value.toFixed(2))} GB`,
		rows: points.map((point) => ({
			time: toDate(point.time),
			Used: point.memory_bytes / 1024 ** 3,
		})),
	},
	getRateChart('network', 'Network', points, [3, 9], {
		Received: (point) => point.received_bytes_per_second,
		Sent: (point) => point.sent_bytes_per_second,
	}),
	getRateChart('disk', 'Disk I/O', points, [2, 7], {
		Read: (point) => point.disk_read_bytes_per_second,
		Write: (point) => point.disk_write_bytes_per_second,
	}),
]
